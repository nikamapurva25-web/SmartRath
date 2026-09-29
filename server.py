"""FastAPI MQTT backend for the local SIH26124 demo."""

import asyncio
from contextlib import contextmanager
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


DB_FILE = os.environ.get("DATABASE_PATH", "backend.db")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "mqtt://localhost:1883")
MQTT_TOPIC = "bus/+/telemetry"
CONGESTION_SPEED_RATIO = 0.60
CONGESTION_COOLDOWN_SECONDS = 60

app = FastAPI(title="SmartRath API | HexaBytes | SIH26124")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clients: List[WebSocket] = []
app.state.mqtt_loop = None


@contextmanager
def connect_db():
    connection = sqlite3.connect(DB_FILE, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                route_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                detection_class TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox TEXT,
                anpr_plate TEXT,
                anpr_confidence REAL,
                network_status TEXT,
                payload_bytes INTEGER,
                accel_g REAL NOT NULL DEFAULT 0,
                vehicle_count INTEGER NOT NULL DEFAULT 0,
                frame_mode TEXT,
                live_speed_kmh REAL
            );
            CREATE INDEX IF NOT EXISTS idx_raw_bus_timestamp
                ON raw_detections(bus_id, timestamp DESC);
            CREATE TABLE IF NOT EXISTS route_speed_baselines (
                route_id TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                segment_name TEXT NOT NULL,
                min_lat REAL NOT NULL,
                max_lat REAL NOT NULL,
                min_lon REAL NOT NULL,
                max_lon REAL NOT NULL,
                baseline_speed_kmh REAL NOT NULL,
                PRIMARY KEY (route_id, segment_id)
            );
            CREATE TABLE IF NOT EXISTS congestion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id TEXT NOT NULL,
                route_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                live_speed_kmh REAL NOT NULL,
                baseline_speed_kmh REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS anpr_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                plate_number TEXT NOT NULL,
                confidence REAL
            );
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                detection_class TEXT NOT NULL,
                cluster_id INTEGER NOT NULL,
                centroid_lat REAL NOT NULL,
                centroid_lon REAL NOT NULL,
                last_updated REAL NOT NULL,
                members_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS od_matrix (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                service_date TEXT NOT NULL,
                generated_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO route_speed_baselines
                (route_id, segment_id, segment_name, min_lat, max_lat, min_lon, max_lon, baseline_speed_kmh)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("R-12", "R-12-CENTRAL", "Pune central demo segment", 18.50, 18.58, 73.80, 73.90, 30.0),
                ("R-18", "R-18-EAST", "Pune east demo segment", 18.48, 18.60, 73.78, 73.95, 32.0),
            ],
        )


def haversine_meters(lat1, lon1, lat2, lon2):
    earth_radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def find_baseline(conn, route_id, lat, lon):
    return conn.execute(
        """
        SELECT baseline_speed_kmh
        FROM route_speed_baselines
        WHERE route_id = ? AND ? BETWEEN min_lat AND max_lat
          AND ? BETWEEN min_lon AND max_lon
        ORDER BY (max_lat - min_lat) * (max_lon - min_lon)
        LIMIT 1
        """,
        (route_id, lat, lon),
    ).fetchone()


def event_message(payload, speed_kmh=None, baseline_speed=None):
    detection = payload["detection"]
    gps = payload["gps"]
    return {
        "type": detection["class"],
        "event_type": "detection",
        "bus_id": payload["bus_id"],
        "route_id": payload["route_id"],
        "timestamp": payload["timestamp"],
        "lat": gps[0],
        "lng": gps[1],
        "confidence": detection["confidence"],
        "bbox": detection.get("bbox"),
        "accel_g": payload.get("imu", {}).get("accel_g", 0),
        "vehicle_count": payload.get("vehicle_count", 0),
        "speed_kmh": speed_kmh,
        "baseline_speed_kmh": baseline_speed,
        "frame_mode": payload.get("frame_mode"),
        "anpr": payload.get("anpr"),
    }


def store_telemetry(payload):
    required = ("bus_id", "timestamp", "route_id", "gps", "detection")
    if any(key not in payload for key in required):
        raise ValueError("Telemetry is missing a required contract field")
    gps = payload["gps"]
    detection = payload["detection"]
    if not isinstance(gps, list) or len(gps) != 2:
        raise ValueError("gps must contain [latitude, longitude]")
    lat, lon = float(gps[0]), float(gps[1])
    timestamp = float(payload["timestamp"])
    speed_kmh = None
    baseline_speed = None
    congestion = None
    anpr_alert = None

    with connect_db() as conn:
        previous = conn.execute(
            "SELECT timestamp, lat, lon FROM raw_detections "
            "WHERE bus_id = ? ORDER BY timestamp DESC LIMIT 1",
            (payload["bus_id"],),
        ).fetchone()
        if previous:
            elapsed = timestamp - previous["timestamp"]
            if 0 < elapsed <= 3600:
                speed_kmh = haversine_meters(
                    previous["lat"], previous["lon"], lat, lon
                ) / elapsed * 3.6

        baseline = find_baseline(conn, payload["route_id"], lat, lon)
        if baseline:
            baseline_speed = float(baseline["baseline_speed_kmh"])

        imu = payload.get("imu") or {}
        anpr = payload.get("anpr") or {}
        conn.execute(
            """
            INSERT INTO raw_detections (
                bus_id, timestamp, route_id, lat, lon, detection_class, confidence,
                bbox, anpr_plate, anpr_confidence, network_status, payload_bytes,
                accel_g, vehicle_count, frame_mode, live_speed_kmh
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["bus_id"], timestamp, payload["route_id"], lat, lon,
                detection["class"], float(detection["confidence"]),
                json.dumps(detection.get("bbox")), anpr.get("plate_number"),
                anpr.get("confidence"), payload.get("network_status"),
                payload.get("payload_bytes"), float(imu.get("accel_g", 0)),
                int(payload.get("vehicle_count", 0)), payload.get("frame_mode"),
                speed_kmh,
            ),
        )

        plate = anpr.get("plate_number")
        if plate:
            conn.execute(
                """
                INSERT INTO anpr_alerts (bus_id, timestamp, lat, lon, plate_number, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (payload["bus_id"], timestamp, lat, lon, plate, anpr.get("confidence")),
            )
            anpr_alert = {
                "event_type": "anpr_alert",
                "type": "ANPR alert",
                "bus_id": payload["bus_id"],
                "timestamp": timestamp,
                "lat": lat,
                "lng": lon,
                "plate_number": plate,
                "confidence": anpr.get("confidence"),
            }

        if (
            speed_kmh is not None
            and baseline_speed is not None
            and speed_kmh < baseline_speed * CONGESTION_SPEED_RATIO
        ):
            last_event = conn.execute(
                """
                SELECT timestamp FROM congestion_events
                WHERE bus_id = ? AND route_id = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (payload["bus_id"], payload["route_id"]),
            ).fetchone()
            if not last_event or timestamp - last_event["timestamp"] >= CONGESTION_COOLDOWN_SECONDS:
                conn.execute(
                    """
                    INSERT INTO congestion_events
                        (bus_id, route_id, timestamp, lat, lon, live_speed_kmh, baseline_speed_kmh)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (payload["bus_id"], payload["route_id"], timestamp, lat, lon, speed_kmh, baseline_speed),
                )
                congestion = {
                    "event_type": "congestion_bottleneck",
                    "type": "congestion_bottleneck",
                    "bus_id": payload["bus_id"],
                    "route_id": payload["route_id"],
                    "timestamp": timestamp,
                    "lat": lat,
                    "lng": lon,
                    "speed_kmh": round(speed_kmh, 1),
                    "baseline_speed_kmh": baseline_speed,
                }

    return event_message(payload, speed_kmh, baseline_speed), congestion, anpr_alert


async def broadcast(payload):
    stale = []
    for websocket in clients:
        try:
            await websocket.send_json(payload)
        except Exception:
            stale.append(websocket)
    for websocket in stale:
        if websocket in clients:
            clients.remove(websocket)


def mqtt_listener(loop):
    if mqtt is None:
        print("paho-mqtt is not installed; MQTT listener is disabled")
        return

    parsed = urlparse(MQTT_BROKER if "://" in MQTT_BROKER else f"mqtt://{MQTT_BROKER}")
    transport = "websockets" if parsed.scheme in ("ws", "wss") else "tcp"
    port = parsed.port or (9001 if transport == "websockets" else 1883)
    client = mqtt.Client(transport=transport)

    def on_connect(mqtt_client, userdata, flags, rc):
        if rc == 0:
            print(f"[mqtt] connected; subscribing to {MQTT_TOPIC}")
            mqtt_client.subscribe(MQTT_TOPIC)
        else:
            print(f"[mqtt] connection rejected with code {rc}")

    def on_message(mqtt_client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            event, congestion, alert = store_telemetry(payload)
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "telemetry", "event": event}), loop
            )
            if congestion:
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "congestion_bottleneck", "event": congestion}), loop
                )
            if alert:
                asyncio.run_coroutine_threadsafe(
                    broadcast({"type": "anpr_alert", "event": alert}), loop
                )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"[mqtt] rejected invalid telemetry on {message.topic}: {exc}")
        except sqlite3.Error as exc:
            print(f"[mqtt] database write failed: {exc}")

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(parsed.hostname or "localhost", port, keepalive=60)
        client.loop_start()
        app.state.mqtt_client = client
    except (OSError, ValueError) as exc:
        print(f"[mqtt] connection failed: {exc}")


def build_od_matrix():
    now = datetime.now(timezone.utc)
    service_date = now.date().isoformat()
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT bus_id, route_id, lat, lon, timestamp
            FROM raw_detections WHERE timestamp >= ?
            ORDER BY bus_id, timestamp
            """,
            (start,),
        ).fetchall()

    trips = {}
    for row in rows:
        key = (row["bus_id"], row["route_id"])
        entry = trips.get(key)
        point = [round(row["lat"], 3), round(row["lon"], 3)]
        if entry is None:
            trips[key] = {"route_id": row["route_id"], "origin": point, "destination": point}
        else:
            entry["destination"] = point

    matrix_counts = {}
    for trip in trips.values():
        key = (trip["route_id"], tuple(trip["origin"]), tuple(trip["destination"]))
        matrix_counts[key] = matrix_counts.get(key, 0) + 1
    matrix = [
        {
            "route_id": route_id,
            "origin": list(origin),
            "destination": list(destination),
            "trips": count,
        }
        for (route_id, origin, destination), count in matrix_counts.items()
    ]
    result = {"date": service_date, "generated_at": time.time(), "matrix": matrix}
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO od_matrix (id, service_date, generated_at, payload)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                service_date = excluded.service_date,
                generated_at = excluded.generated_at,
                payload = excluded.payload
            """,
            (service_date, result["generated_at"], json.dumps(result)),
        )
    return result


@app.on_event("startup")
async def startup_event():
    init_db()
    loop = asyncio.get_running_loop()
    app.state.mqtt_loop = loop
    loop.run_in_executor(None, mqtt_listener, loop)
    app.state.cluster_task = asyncio.create_task(cluster_worker())
    app.state.od_task = asyncio.create_task(od_matrix_worker())


@app.on_event("shutdown")
async def shutdown_event():
    for name in ("cluster_task", "od_task"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()
    client = getattr(app.state, "mqtt_client", None)
    if client:
        client.loop_stop()
        client.disconnect()


@app.get("/")
def root():
    return {"message": "SmartRath API by HexaBytes is running", "problem_statement": "SIH26124"}


@app.get("/api/events")
def get_events():
    with connect_db() as conn:
        clusters = conn.execute(
            """
            SELECT event_type, detection_class, cluster_id, centroid_lat, centroid_lon,
                   last_updated, members_count
            FROM clusters ORDER BY last_updated DESC
            """
        ).fetchall()
        alerts = conn.execute(
            """
            SELECT id, bus_id, timestamp, lat, lon, plate_number, confidence
            FROM anpr_alerts ORDER BY timestamp DESC LIMIT 100
            """
        ).fetchall()
        buses = conn.execute(
            """
            SELECT d.bus_id, d.route_id, d.lat, d.lon, d.timestamp, d.live_speed_kmh,
                   d.vehicle_count, b.baseline_speed_kmh
            FROM raw_detections d
            LEFT JOIN route_speed_baselines b ON b.route_id = d.route_id
            WHERE d.id IN (
                SELECT MAX(id) FROM raw_detections GROUP BY bus_id
            )
            """
        ).fetchall()
    events = [
        {
            "id": f"{row['event_type']}-{row['cluster_id']}",
            "event_type": row["event_type"],
            "type": row["detection_class"],
            "lat": row["centroid_lat"],
            "lng": row["centroid_lon"],
            "timestamp": row["last_updated"],
            "members": row["members_count"],
        }
        for row in clusters
    ]
    events.extend(
        {
            "id": f"anpr-{row['id']}",
            "event_type": "anpr_alert",
            "type": "ANPR alert",
            "bus_id": row["bus_id"],
            "timestamp": row["timestamp"],
            "lat": row["lat"],
            "lng": row["lon"],
            "plate_number": row["plate_number"],
            "confidence": row["confidence"],
        }
        for row in alerts
    )
    return {
        "events": events,
        "buses": [
            {
                "bus_id": row["bus_id"],
                "route_id": row["route_id"],
                "lat": row["lat"],
                "lng": row["lon"],
                "timestamp": row["timestamp"],
                "speed_kmh": row["live_speed_kmh"],
                "baseline_speed_kmh": row["baseline_speed_kmh"],
                "vehicle_count": row["vehicle_count"],
            }
            for row in buses
        ],
    }


@app.get("/api/stats")
def get_stats():
    with connect_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM raw_detections").fetchone()[0]
        critical = conn.execute(
            "SELECT COUNT(*) FROM raw_detections WHERE detection_class LIKE '%pothole%'"
        ).fetchone()[0]
        routes = conn.execute("SELECT COUNT(DISTINCT route_id) FROM raw_detections").fetchone()[0]
        confidence = conn.execute("SELECT AVG(confidence) FROM raw_detections").fetchone()[0] or 0
    return {
        "total_events": total,
        "critical_issues": critical,
        "routes_monitored": routes,
        "ai_confidence": round(confidence * 100, 1),
    }


@app.get("/api/detections")
def get_detections():
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT id, bus_id, route_id, detection_class, confidence, lat, lon,
                   timestamp, accel_g, live_speed_kmh, frame_mode
            FROM raw_detections ORDER BY timestamp DESC LIMIT 1
            """
        ).fetchone()
    if not row:
        return {"status": "idle", "model": "YOLOv8-nano urban", "detections": []}
    return {
        "status": "processing",
        "model": "YOLOv8-nano urban",
        "detections": [{
            "id": row["id"], "bus_id": row["bus_id"], "route": row["route_id"],
            "type": row["detection_class"], "confidence": int(row["confidence"] * 100),
            "lat": row["lat"], "lng": row["lon"], "timestamp": row["timestamp"],
            "accel_g": row["accel_g"], "speed_kmh": row["live_speed_kmh"],
            "frame_mode": row["frame_mode"],
        }],
    }


@app.get("/api/od-matrix")
def get_od_matrix():
    with connect_db() as conn:
        row = conn.execute("SELECT payload FROM od_matrix WHERE id = 1").fetchone()
    return json.loads(row["payload"]) if row else build_od_matrix()


@app.get("/api/routes/baselines")
def get_route_baselines():
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM route_speed_baselines ORDER BY route_id").fetchall()
    return [dict(row) for row in rows]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in clients:
            clients.remove(websocket)


async def cluster_worker():
    try:
        from sklearn.cluster import DBSCAN
        import numpy as np
    except ImportError:
        print("scikit-learn and numpy are required for DBSCAN clustering")
        return

    while True:
        try:
            with connect_db() as conn:
                infrastructure = conn.execute(
                    """
                    SELECT lat, lon, detection_class FROM raw_detections
                    WHERE detection_class IN ('pothole_severe', 'pothole_mild', 'signage_damage', 'waterlogging')
                    """
                ).fetchall()
                congestion = conn.execute(
                    "SELECT lat, lon FROM congestion_events"
                ).fetchall()

            grouped = []
            for event_type, rows, classes in (
                ("infrastructure", infrastructure, True),
                ("congestion_bottleneck", congestion, False),
            ):
                if len(rows) < 2:
                    continue
                coords = np.array([[row["lat"], row["lon"]] for row in rows])
                labels = DBSCAN(eps=0.00015, min_samples=2, metric="euclidean").fit_predict(coords)
                for cluster_id in set(labels):
                    if cluster_id < 0:
                        continue
                    members = [index for index, label in enumerate(labels) if label == cluster_id]
                    latitude = float(np.mean(coords[members, 0]))
                    longitude = float(np.mean(coords[members, 1]))
                    label = (
                        max(
                            (rows[index]["detection_class"] for index in members),
                            key=lambda value: sum(rows[i]["detection_class"] == value for i in members),
                        )
                        if classes else "congestion_bottleneck"
                    )
                    grouped.append((event_type, label, int(cluster_id), latitude, longitude, time.time(), len(members)))

            with connect_db() as conn:
                conn.execute("DELETE FROM clusters")
                conn.executemany(
                    """
                    INSERT INTO clusters
                        (event_type, detection_class, cluster_id, centroid_lat, centroid_lon, last_updated, members_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    grouped,
                )
            await broadcast({"type": "clusters_update", "clusters": [
                {
                    "event_type": item[0], "detection_class": item[1],
                    "cluster_id": item[2], "lat": item[3], "lng": item[4],
                    "members": item[6],
                }
                for item in grouped
            ]})
        except (sqlite3.Error, ValueError) as exc:
            print(f"[cluster_worker] failed: {exc}")
        await asyncio.sleep(10)


async def od_matrix_worker():
    while True:
        try:
            build_od_matrix()
        except sqlite3.Error as exc:
            print(f"[od_matrix_worker] failed: {exc}")
        await asyncio.sleep(60)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
