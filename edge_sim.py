"""CPU edge simulator with optional OpenCV + ONNX Runtime detection.

The simulator never uploads video. It samples local frames at ``--fps``, keeps
frames in RAM, emits only compact detections, and queues telemetry in SQLite
when the broker/network is unavailable.
"""

import argparse
import csv
from contextlib import contextmanager
import json
import math
import random
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    import onnxruntime as ort
except ImportError:
    ort = None

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


DB_PATH = "edge_queue.db"
DEFAULT_LABELS = (
    "pothole_severe",
    "pothole_mild",
    "signage_damage",
    "waterlogging",
    "vehicle",
    "pedestrian_risk",
)
INFRASTRUCTURE_CLASSES = {"pothole_severe", "pothole_mild", "signage_damage", "waterlogging"}
TRAFFIC_CLASSES = {"vehicle", "car", "bus", "truck", "motorcycle", "pedestrian", "pedestrian_risk"}


def frame_mode_for_sample(sample_number):
    return "infrastructure" if (sample_number - 1) % 2 == 0 else "traffic"



def estimate_payload_bytes(payload):
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


@contextmanager
def connect_queue_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with connect_queue_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS queued_telemetry "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL, queued_at INTEGER NOT NULL)"
        )


def queue_payload(payload):
    with connect_queue_db() as conn:
        conn.execute(
            "INSERT INTO queued_telemetry (payload, queued_at) VALUES (?, ?)",
            (json.dumps(payload, separators=(",", ":")), int(time.time())),
        )


def queued_payloads():
    with connect_queue_db() as conn:
        return conn.execute(
            "SELECT id, payload FROM queued_telemetry ORDER BY id ASC"
        ).fetchall()


def remove_queued(row_id):
    with connect_queue_db() as conn:
        conn.execute("DELETE FROM queued_telemetry WHERE id = ?", (row_id,))


class OnnxDetector:
    """Small generic YOLO ONNX adapter for common Ultralytics exports."""

    def __init__(self, model_path, labels):
        if ort is None or np is None or cv2 is None:
            raise RuntimeError("onnxruntime, numpy, and opencv-python are required for ONNX inference")
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        shape = self.session.get_inputs()[0].shape
        self.input_size = int(shape[-1]) if isinstance(shape[-1], int) else 640
        self.labels = labels

    def detect(self, frame, confidence_threshold=0.35):
        height, width = frame.shape[:2]
        resized = cv2.resize(frame, (self.input_size, self.input_size))
        tensor = resized[:, :, ::-1].astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        outputs = self.session.run(None, {self.input_name: tensor})
        raw = np.asarray(outputs[0])
        raw = np.squeeze(raw)
        if raw.ndim != 2:
            return None
        if raw.shape[0] < raw.shape[1]:
            raw = raw.T

        detections = []
        for row in raw:
            if row.size < 6:
                continue
            if row.size == 4 + len(self.labels):
                objectness = 1.0
                class_scores = row[4:]
            else:
                objectness = float(row[4])
                class_scores = row[5:]
            class_index = int(np.argmax(class_scores))
            score = objectness * float(class_scores[class_index])
            if score < confidence_threshold:
                continue
            x, y, box_width, box_height = row[:4]
            scale_x = width / self.input_size
            scale_y = height / self.input_size
            if max(abs(float(x)), abs(float(y)), abs(float(box_width)), abs(float(box_height))) <= 2:
                scale_x *= self.input_size
                scale_y *= self.input_size
            x1 = max(0, int((x - box_width / 2) * scale_x))
            y1 = max(0, int((y - box_height / 2) * scale_y))
            x2 = min(width, int((x + box_width / 2) * scale_x))
            y2 = min(height, int((y + box_height / 2) * scale_y))
            label = self.labels[class_index] if class_index < len(self.labels) else f"class_{class_index}"
            detections.append((label, round(score, 2), [x1, y1, x2, y2]))
        return detections


class EdgeSimulator:
    def __init__(
        self,
        bus_id,
        route_id,
        broker,
        fps=5,
        video_path=None,
        model_path=None,
        labels=None,
        offline_probability=0.1,
        imu_path=None,
        imu_threshold_g=1.5,
        enable_anpr=False,
        ocr_engine="easyocr",
        speed_kmh=30.0,
    ):
        self.bus_id = bus_id
        self.route_id = route_id
        self.broker = broker
        self.fps = max(1, min(10, fps))
        self.video_path = Path(video_path) if video_path else None
        self.detector = OnnxDetector(model_path, labels or DEFAULT_LABELS) if model_path else None
        self.offline_probability = max(0.0, min(1.0, offline_probability))
        self.imu_samples = self.load_imu_samples(imu_path)
        self.imu_index = 0
        self.imu_threshold_g = imu_threshold_g
        self.enable_anpr = enable_anpr
        self.ocr_engine = ocr_engine
        self.ocr_reader = None
        self.last_gps = (18.5204, 73.8567)
        self.last_gps_timestamp = time.time()
        self.gps_speed_kmh = max(0.0, speed_kmh)
        self.client = None
        self.connected = False
        self.stop_event = threading.Event()
        init_db()

    @staticmethod
    def load_imu_samples(imu_path):
        if not imu_path:
            return [0.0]
        path = Path(imu_path)
        if not path.is_file():
            raise FileNotFoundError(f"IMU sample file not found: {path}")
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            samples = [float(row["accel_g"]) for row in rows if row.get("accel_g")]
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("samples", [])
            samples = [
                float(item["accel_g"] if isinstance(item, dict) else item)
                for item in data
            ]
        if not samples:
            raise ValueError(f"IMU file contains no accel_g samples: {path}")
        return samples

    def next_imu_g(self):
        value = self.imu_samples[self.imu_index % len(self.imu_samples)]
        self.imu_index += 1
        return value

    def next_gps(self, now):
        elapsed = max(0.0, now - self.last_gps_timestamp)
        distance_m = self.gps_speed_kmh * elapsed / 3.6
        lat, lon = self.last_gps
        # Move along a short north-east demo route at the simulated bus speed.
        lat += distance_m / 111_320
        lon += distance_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
        self.last_gps = (lat, lon)
        self.last_gps_timestamp = now
        return [round(lat, 6), round(lon, 6)]

    def read_plate(self, frame, vehicle_boxes):
        if not self.enable_anpr or not vehicle_boxes:
            return {"plate_number": None, "confidence": None}
        if self.ocr_reader is None:
            if self.ocr_engine == "easyocr":
                try:
                    import easyocr
                except ImportError as exc:
                    raise RuntimeError("Conditional ANPR was triggered; install easyocr to run --enable-anpr") from exc
                self.ocr_reader = easyocr.Reader(["en"], gpu=False)
            else:
                try:
                    from paddleocr import PaddleOCR
                except ImportError as exc:
                    raise RuntimeError("Conditional ANPR was triggered; install paddleocr to run --enable-anpr") from exc
                self.ocr_reader = PaddleOCR(use_angle_cls=False, lang="en")
        if cv2 is None:
            raise RuntimeError("OpenCV is required to crop a vehicle region for ANPR")
        x1, y1, x2, y2 = max(vehicle_boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return {"plate_number": None, "confidence": None}
        if self.ocr_engine == "easyocr":
            results = self.ocr_reader.readtext(crop)
            if not results:
                return {"plate_number": None, "confidence": None}
            text, confidence = max(((item[1], float(item[2])) for item in results), key=lambda item: item[1])
        else:
            results = self.ocr_reader.ocr(crop, cls=False)
            candidates = [line[1] for group in results or [] for line in (group or [])]
            if not candidates:
                return {"plate_number": None, "confidence": None}
            text, confidence = max(((item[0], float(item[1])) for item in candidates), key=lambda item: item[1])
        normalized = "".join(character for character in text.upper() if character.isalnum())
        return {"plate_number": normalized or None, "confidence": round(confidence, 2) if normalized else None}

    def anpr_for_frame(self, frame, imu_g, vehicle_boxes):
        if not self.enable_anpr or imu_g <= self.imu_threshold_g or not vehicle_boxes:
            return {"plate_number": None, "confidence": None}
        return self.read_plate(frame, vehicle_boxes)

    def on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0
        print(f"[mqtt] connected={self.connected} rc={rc}")

    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        print(f"[mqtt] disconnected rc={rc}")

    def start_mqtt(self):
        if mqtt is None:
            print("[mqtt] paho-mqtt is not installed; telemetry will remain queued")
            return
        parsed = urlparse(self.broker if "://" in self.broker else f"mqtt://{self.broker}")
        transport = "websockets" if parsed.scheme in ("ws", "wss") else "tcp"
        port = parsed.port or (9001 if transport == "websockets" else 1883)
        self.client = mqtt.Client(transport=transport)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        try:
            self.client.connect(parsed.hostname or "localhost", port, keepalive=60)
            threading.Thread(target=self.client.loop_forever, daemon=True).start()
        except (OSError, ValueError) as exc:
            print(f"[mqtt] connect error: {exc}")

    def publish(self, payload):
        if not self.client or not self.connected:
            queue_payload(payload)
            return False
        info = self.client.publish(f"bus/{self.bus_id}/telemetry", json.dumps(payload, separators=(",", ":")))
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            queue_payload(payload)
            return False
        return True

    def flush_local_queue(self):
        if not self.client or not self.connected:
            return
        for row_id, serialized in queued_payloads():
            info = self.client.publish(f"bus/{self.bus_id}/telemetry", serialized)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return
            remove_queued(row_id)

    def synthetic_detection(self):
        return (
            random.choice(DEFAULT_LABELS),
            round(random.uniform(0.7, 0.99), 2),
            [random.randint(50, 200), random.randint(200, 400), random.randint(220, 420), random.randint(420, 640)],
        )

    def synthetic_model_frame(self, sample_number):
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        detections = self.detector.detect(frame)
        frame_mode = frame_mode_for_sample(sample_number)
        allowed = INFRASTRUCTURE_CLASSES if frame_mode == "infrastructure" else TRAFFIC_CLASSES
        selected = [item for item in detections or [] if item[0] in allowed]
        imu_g = self.next_imu_g()
        vehicle_boxes = [
            box for label, _, box in detections or []
            if label in {"vehicle", "car", "bus", "truck", "motorcycle"}
        ]
        anpr = self.anpr_for_frame(frame, imu_g, vehicle_boxes)
        detection = selected[0] if selected else self.synthetic_detection()
        return detection, imu_g, anpr, frame_mode

    def telemetry(self, detection, *, imu_g=0.0, anpr=None):
        label, confidence, bbox = detection
        now = time.time()
        gps = self.next_gps(now)
        payload = {
            "bus_id": self.bus_id,
            "timestamp": round(now, 3),
            "route_id": self.route_id,
            "gps": gps,
            "detection": {"class": label, "confidence": confidence, "bbox": bbox},
            "anpr": anpr or {"plate_number": None, "confidence": None},
            "imu": {"accel_g": round(imu_g, 2)},
            "vehicle_count": 1 if label in TRAFFIC_CLASSES else 0,
            "network_status": "OFFLINE" if random.random() < self.offline_probability else "ONLINE",
            "payload_bytes": 0,
        }
        payload["payload_bytes"] = estimate_payload_bytes(payload)
        if payload["payload_bytes"] >= 1024:
            raise ValueError(f"Telemetry payload exceeds 1 KB: {payload['payload_bytes']} bytes")
        return payload

    def process_video(self):
        if cv2 is None or not self.video_path:
            return
        capture = cv2.VideoCapture(str(self.video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open video: {self.video_path}")
        source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_step = max(1, round(source_fps / self.fps))
        frame_index = 0
        try:
            while not self.stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    break
                frame_index += 1
                if frame_index % frame_step:
                    continue
                sampled_frame = frame_index // frame_step
                frame_mode = frame_mode_for_sample(sampled_frame)
                imu_g = self.next_imu_g()
                detections = self.detector.detect(frame) if self.detector else [self.synthetic_detection()]
                allowed = INFRASTRUCTURE_CLASSES if frame_mode == "infrastructure" else TRAFFIC_CLASSES
                selected = [item for item in detections if item[0] in allowed]
                vehicle_boxes = [box for label, _, box in detections if label in {"vehicle", "car", "bus", "truck", "motorcycle"}]
                anpr = self.anpr_for_frame(frame, imu_g, vehicle_boxes)
                if anpr["plate_number"]:
                    selected.extend(
                        detection for detection in detections
                        if detection[0] in {"vehicle", "car", "bus", "truck", "motorcycle"}
                    )
                for detection in selected:
                    yield detection, imu_g, anpr, frame_mode
                time.sleep(1.0 / self.fps)
        finally:
            capture.release()

    def run(self):
        self.start_mqtt()
        detections = self.process_video() if self.video_path else None
        sample_number = 0
        try:
            while not self.stop_event.is_set():
                if detections:
                    item = next(detections, None)
                elif self.detector:
                    sample_number += 1
                    item = self.synthetic_model_frame(sample_number)
                else:
                    item = (
                        self.synthetic_detection(), self.next_imu_g(),
                        {"plate_number": None, "confidence": None}, "infrastructure",
                    )
                if item:
                    detection, imu_g, anpr, frame_mode = item
                    payload = self.telemetry(detection, imu_g=imu_g, anpr=anpr)
                    payload["frame_mode"] = frame_mode
                    payload["payload_bytes"] = estimate_payload_bytes(payload)
                    if payload["payload_bytes"] >= 1024:
                        raise ValueError(f"Telemetry payload exceeds 1 KB: {payload['payload_bytes']} bytes")
                    if payload["network_status"] == "OFFLINE":
                        queue_payload(payload)
                    else:
                        self.publish(payload)
                    self.flush_local_queue()
                    print(f"[edge_sim] {payload['detection']['class']} {payload['payload_bytes']} bytes {payload['network_status']}")
                if not detections:
                    time.sleep(1.0 / self.fps)
        except KeyboardInterrupt:
            pass

    def stop(self):
        self.stop_event.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bus-id", default="BEST-104")
    parser.add_argument("--route", default="R-12")
    parser.add_argument("--broker", default="mqtt://localhost:1883", help="mqtt://host:1883 or ws://host:9001")
    parser.add_argument("--fps", type=int, default=5, help="Frame sampling rate, capped at 10 FPS")
    parser.add_argument("--video", help="Local MP4 path; frames are processed only in RAM")
    parser.add_argument("--model", help="YOLO ONNX model path; enables CPU inference")
    parser.add_argument("--labels", help="Optional newline-delimited class labels")
    parser.add_argument("--imu-file", help="JSON or CSV file containing simulated accel_g samples")
    parser.add_argument("--imu-threshold-g", type=float, default=1.5)
    parser.add_argument("--enable-anpr", action="store_true", help="Enable OCR only when IMU threshold and vehicle-box conditions are both met")
    parser.add_argument("--ocr-engine", choices=("easyocr", "paddleocr"), default="easyocr")
    parser.add_argument("--speed-kmh", type=float, default=30.0, help="Simulated bus speed; use a value below 60%% of route baseline to demo congestion")
    parser.add_argument("--offline-probability", type=float, default=0.1)
    args = parser.parse_args()
    labels = Path(args.labels).read_text(encoding="utf-8").splitlines() if args.labels else None
    EdgeSimulator(
        args.bus_id, args.route, args.broker, args.fps, args.video, args.model,
        labels, args.offline_probability, args.imu_file, args.imu_threshold_g,
        args.enable_anpr, args.ocr_engine, args.speed_kmh,
    ).run()


if __name__ == "__main__":
    main()
