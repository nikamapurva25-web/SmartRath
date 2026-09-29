# SmartRath — HexaBytes | SIH26124

**SmartRath** is HexaBytes' Smart India Hackathon prototype for problem
statement **SIH26124**: an offline-feasible urban intelligence platform for
road hazard reporting, public transport monitoring, and commuter safety.

It demonstrates local edge processing and city operations in a laptop-sized
demo. Video stays on the edge simulator; only compact event telemetry is sent
to the backend. The system is a prototype, not a production safety service or
an official SIH submission by itself.

## What SmartRath demonstrates

- **Edge-first, offline-tolerant telemetry:** local video frame sampling,
  optional CPU ONNX inference, IMU-triggered OCR, and an SQLite queue for
  broker outages.
- **Multi-bus event aggregation:** MQTT telemetry flows to FastAPI and is
  spatially grouped with DBSCAN before clusters appear as dashboard incidents.
- **Traffic and route analytics:** route speed baselines, congestion events,
  and a daily origin-destination summary.
- **A map-based command dashboard:** live bus positions, infrastructure
  clusters, and safety alerts using React and MapLibre GL JS.
- **Optional field dispatch:** a separate, explicitly opt-in WhatsApp gateway
  and cluster snapshot helper.

## Stack

| Component | Technology | Local endpoint |
| --- | --- | --- |
| MQTT broker | Eclipse Mosquitto, MQTT and WebSockets | `localhost:1883`, `localhost:9001` |
| Edge simulator | Python, OpenCV, ONNX Runtime, SQLite queue | Local process |
| API and analytics | FastAPI, Uvicorn, SQLite, scikit-learn DBSCAN | `http://localhost:8000` |
| Operations dashboard | React, Vite, MapLibre GL JS, Recharts | `http://localhost:5173` |
| Optional field dispatcher | Node.js, whatsapp-web.js | `http://localhost:3001` |

## Start quickly

Prerequisites: Python 3.10+, Node.js 22+, npm, and Docker Desktop with Compose.
The included PowerShell launcher starts the broker, backend, toy-model
simulator, and dashboard in separate terminals:

```powershell
python -m pip install -r requirements.txt
npm --prefix frontend ci
.\launch_demo.ps1
```

Alternatively, follow the detailed [setup and operating guide](#setup-and-run)
to start components individually and use a local video/model.

The repository includes a tiny deterministic ONNX fixture for smoke tests. It
is not a trained model and its detections are not evidence of real-world
performance.

## Team

| | |
| --- | --- |
| Platform | **SmartRath** |
| Team | **HexaBytes** |
| Hackathon problem statement | **SIH26124** |

Please replace this table with team member names and official SIH details only
after confirming them with the full team.

## Architecture

The local stack consists of:

1. **Eclipse Mosquitto** — local MQTT broker with native MQTT on `1883` and
   MQTT over WebSockets on `9001`.
2. **`edge_sim.py`** — on-bus simulator with synthetic detections or optional
   OpenCV + CPU ONNX Runtime inference, frame multiplexing, simulated IMU data,
   and interrupt-driven ANPR. It queues unsent telemetry in SQLite.
3. **`server.py`** — FastAPI backend that consumes `bus/+/telemetry`, stores
   detections in SQLite, runs DBSCAN spatial clustering every 10 seconds, and
   exposes REST/WebSocket endpoints.
4. **React + MapLibre dashboard** — Vite dashboard with MapLibre GL JS and
   Recharts for command-and-control visualization.

The optional [`whatsapp_bot.js`](./whatsapp_bot.js) gateway can dispatch
field alerts through `whatsapp-web.js`.

For a four-window Windows demo launch, see
[`launch_demo.ps1`](./launch_demo.ps1). The repository also includes a tiny
static-output ONNX model and a safe-by-default DBSCAN-cluster dispatch helper.

## Setup and run

The expanded launch instructions below document component-by-component setup.
The directory is intentionally not expected to contain a checked-in Python
virtual environment; create one locally and install dependencies as described.

## Architecture diagram

```text
Local MP4 / camera
        |
        v
edge_sim.py
  OpenCV frame sampling + infrastructure/traffic multiplexing
  one CPU ONNX inference pass per sampled frame
  optional IMU-gated OCR when a vehicle is detected
  compact JSON telemetry
        |
        | MQTT on localhost:1883
        | MQTT over WebSockets on localhost:9001
        v
Eclipse Mosquitto
        |
        v
server.py
  SQLite raw detections
  DBSCAN(eps=0.00015, min_samples=2)
  segment speed baselines, congestion bottlenecks, daily O-D matrix
  REST API :8000
  WebSocket /ws
        |
        v
React + MapLibre dashboard :5173
```

### Data-flow constraints

- No RTSP, MP4, or raw camera frame is uploaded to the backend.
- Frames are sampled locally and discarded from RAM after processing.
- Telemetry is published on `bus/<BUS_ID>/telemetry`.
- A telemetry event is designed to remain below the strict 1 KB ceiling.
- Offline edge events are written to `edge_queue.db` and flushed after
  reconnecting to MQTT.
- Spatial deduplication is performed with DBSCAN using `eps=0.00015` and
  `min_samples=2`.
- Frame inference alternates infrastructure and traffic/safety class focus to
  keep CPU work bounded while reusing a single unified ONNX model.
- OCR is opt-in and remains dormant unless `--enable-anpr` is set, simulated
  acceleration exceeds the configured threshold, and a vehicle box is present.

### Prerequisites

Install the following on the demo laptop:

- Windows 10/11, macOS, or Linux
- Python 3.10+
- Docker Desktop with Docker Compose
- Node.js 22+ and npm
- Git

Optional edge inference dependencies:

- `opencv-python`
- `numpy`
- `onnxruntime`

Optional model assets:

- A compatible YOLOv8/YOLOv11 ONNX model
- A newline-delimited labels file

### 1. Install Python dependencies

From the repository root:

### Windows PowerShell

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If the repository does not contain `venv`, create it first:

```powershell
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Linux/macOS

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`scikit-learn` and `numpy` are required for DBSCAN clustering. OpenCV and
ONNX Runtime are only needed when running the simulator with a local video and
model.

### 2. Start the Mosquitto broker

From the repository root:

```powershell
docker compose up -d
```

Confirm that the broker is running:

```powershell
docker compose ps
docker compose logs mosquitto
```

Expected exposed ports:

| Port | Protocol | Purpose |
| --- | --- | --- |
| `1883` | MQTT/TCP | Default path used by `edge_sim.py` and `server.py` |
| `9001` | MQTT/WebSockets | Browser-compatible MQTT transport and optional edge transport |

The broker configuration is in
[`mosquitto.conf`](./mosquitto.conf), and the Compose service is in
[`docker-compose.yml`](./docker-compose.yml).

The prototype intentionally uses anonymous local access. Do not expose these
ports directly to the public internet without adding authentication, TLS, and
network restrictions.

### 3. Start the FastAPI backend

Open a second terminal at the repository root, activate the same environment,
and run:

```powershell
.\venv\Scripts\Activate.ps1
python server.py
```

The backend listens on:

- REST API: `http://localhost:8000`
- WebSocket: `ws://localhost:8000/ws`

The backend subscribes to:

```text
bus/+/telemetry
```

By default it connects to native MQTT at `mqtt://localhost:1883`. To use the
WebSocket listener instead:

```powershell
$env:MQTT_BROKER = "ws://localhost:9001"
python server.py
```

Useful smoke checks:

```powershell
Invoke-RestMethod http://localhost:8000/
Invoke-RestMethod http://localhost:8000/api/events
Invoke-RestMethod http://localhost:8000/api/stats
Invoke-RestMethod http://localhost:8000/api/detections
```

The backend creates `backend.db` in the current working directory. It
contains:

- `raw_detections` — compact event records received from the edge.
- `clusters` — the latest DBSCAN cluster summaries.
- `route_speed_baselines` — seeded local demo speed baselines for `R-12` and
  `R-18`, keyed by route segment.
- `congestion_events` — live-speed drops of at least 40% against a matching
  route-segment baseline.
- `anpr_alerts` — OCR results emitted only after the IMU/vehicle trigger.
- `od_matrix` — periodically refreshed daily origin/destination aggregate.

The DBSCAN worker runs every 10 seconds. At least two nearby detections are
required for a cluster.

Daily origin/destination summaries are refreshed every minute and are
available from `GET http://localhost:8000/api/od-matrix`.

### 4. Start one or more edge simulators

Open a third terminal, activate the Python environment, and start the default
synthetic simulator:

```powershell
.\venv\Scripts\Activate.ps1
python edge_sim.py `
  --bus-id BEST-104 `
  --route R-12 `
  --broker mqtt://localhost:1883 `
  --fps 5 `
  --imu-file .\data\imu_samples.json
```

The simulator prints the detection class, payload size, and network state.
Press `Ctrl+C` to stop it.

To simulate multiple buses, start additional terminals with different bus IDs:

```powershell
python edge_sim.py --bus-id BEST-105 --route R-12 --broker mqtt://localhost:1883 --fps 5
python edge_sim.py --bus-id BEST-201 --route R-18 --broker mqtt://localhost:1883 --fps 5
```

Each simulator publishes to its own topic:

```text
bus/BEST-104/telemetry
bus/BEST-105/telemetry
bus/BEST-201/telemetry
```

### Simulate cellular dead zones

Increase the probability of offline events:

```powershell
python edge_sim.py `
  --bus-id BEST-104 `
  --route R-12 `
  --broker mqtt://localhost:1883 `
  --offline-probability 0.5 `
  --fps 5
```

Offline events are stored in `edge_queue.db`. When connectivity is available,
queued events are published and removed from the local queue.

The IMU file can be a JSON array of G-force readings or an object containing a
`samples` array:

```json
{
  "samples": [
    {"accel_g": 0.2},
    {"accel_g": 0.4},
    {"accel_g": 1.8}
  ]
}
```

CSV files with an `accel_g` column are also supported.

### Demonstrate congestion detection

The seeded `R-12` baseline is 30 km/h. Simulate a bus moving below 60% of that
baseline to generate a `congestion_bottleneck` event:

```powershell
python edge_sim.py --bus-id BEST-SLOW --route R-12 --speed-kmh 12 --offline-probability 0
```

Computed speeds, congestion events, and baselines are also available through
the WebSocket feed and `GET /api/routes/baselines`.

### Process a local MP4 with CPU ONNX inference

The simulator does not upload the video. It reads frames locally, samples
frames at the requested rate, runs inference on CPU, and emits only detections:

```powershell
python edge_sim.py `
  --bus-id BEST-104 `
  --route R-12 `
  --broker mqtt://localhost:1883 `
  --video .\media\bus_front.mp4 `
  --model .\models\yolov8n.onnx `
  --labels .\models\labels.txt `
  --fps 5 `
  --imu-file .\data\imu_samples.json `
  --enable-anpr `
  --imu-threshold-g 1.5
```

ONNX inference alternates sampled frames between infrastructure classes
(`pothole_*`, signage, waterlogging) and traffic/safety classes (vehicles and
pedestrians). ANPR OCR is loaded only when enabled and a sample exceeds the
G-force threshold while containing a vehicle detection. To install one OCR
engine, use either `python -m pip install easyocr` or
`python -m pip install paddleocr`; neither is needed for the base demo.

The labels file must contain one class name per line, for example:

```text
pothole_severe
pothole_mild
signage_damage
waterlogging
vehicle
pedestrian
pedestrian_risk
```

The ONNX adapter expects a common YOLO export with an input tensor shaped like
`1x3x640x640` and detection rows containing box coordinates, objectness, and
class scores. Model-specific exports may require adapting
`OnnxDetector.detect()` in [`edge_sim.py`](./edge_sim.py).

### Run with the included toy ONNX model

The repository contains [`models/toy_yolo.onnx`](./models/toy_yolo.onnx) and
its matching [`models/labels.txt`](./models/labels.txt). This 602-byte model
is a deterministic smoke-test fixture: it returns one fixed pothole and one
fixed vehicle detection regardless of the input pixels. It is not a trained
hazard detector and must not be used for real-world decisions.

No video file is needed for this fixture. If `--model` is provided without
`--video`, the simulator feeds zero-filled frames from RAM through ONNX Runtime
and continues to alternate infrastructure/traffic event focus:

```powershell
python edge_sim.py `
  --bus-id BEST-104 `
  --route R-12 `
  --model .\models\toy_yolo.onnx `
  --labels .\models\labels.txt `
  --fps 5 `
  --offline-probability 0
```

OpenCV, NumPy, and ONNX Runtime are still required (`requirements.txt`
includes them). The model is small enough to ship in the repository and makes
it possible to test model loading and telemetry end-to-end without downloading
a pretrained model.

The simulator accepts WebSockets as an alternative:

```powershell
python edge_sim.py --broker ws://localhost:9001 --bus-id BEST-104 --route R-12
```

### 5. Start the React MapLibre dashboard

Open a fourth terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite, normally:

```text
http://localhost:5173
```

The dashboard loads initial summaries from `http://127.0.0.1:8000/api` and
receives live telemetry over `ws://127.0.0.1:8000/ws`. Use the layer controls
to switch between:

- **Infrastructure** — DBSCAN hazard clusters as a heatmap.
- **Traffic** — live bus positions/trails, vehicle counts, and baseline-relative
  green/red speed status.
- **Safety** — pulsating red icons for conditional ANPR and pedestrian-risk
  alerts.

The daily O-D panel reads the aggregated `/api/od-matrix` endpoint. Start
`server.py` before opening the dashboard so live telemetry is available.

The map uses MapLibre GL JS. Leaflet is not part of the required dashboard
mapping path.

For a production-style static build:

```powershell
npm run build
npm run preview
```

### Optional: WhatsApp field dispatcher

The optional gateway in [`whatsapp_bot.js`](./whatsapp_bot.js) is independent
of the core four-process launch:

```powershell
npm install whatsapp-web.js express body-parser qrcode-terminal
node whatsapp_bot.js
```

Scan the displayed QR code on first launch. The gateway listens on port
`3001` and accepts:

```http
POST http://localhost:3001/api/dispatch-alert
Content-Type: application/json
```

Example request:

```json
{
  "to": "919XXXXXXXXX",
  "message": "Severe pothole detected by BEST-104.",
  "google_maps_url": "https://www.google.com/maps?q=18.5204,73.8567",
  "image_base64": "data:image/jpeg;base64,..."
}
```

This gateway requires a WhatsApp account and a locally authenticated browser
session. It is not required to run the MQTT, backend, or dashboard demo.

### Dispatch a snapshot of current DBSCAN clusters

[`dispatch_clusters.py`](./dispatch_clusters.py) reads the current
`/api/events` snapshot, selects infrastructure and congestion DBSCAN clusters,
and prepares one WhatsApp payload per cluster with hazard details and a
Google Maps navigation link. The default is a dry run and does not contact the
WhatsApp gateway:

```powershell
python .\dispatch_clusters.py `
  --to 919XXXXXXXXX `
  --snapshot-file .\dispatch_snapshot.json
```

After starting and authenticating `whatsapp_bot.js`, send the prepared alerts
by adding `--send`:

```powershell
python .\dispatch_clusters.py --to 919XXXXXXXXX --send
```

The helper calls `GET http://localhost:8000/api/events`, then posts each
payload to `POST http://localhost:3001/api/dispatch-alert`. Use a recipient
number with country code. Review the dry run before sending; this sends real
WhatsApp messages. The prototype does not retain hazard image crops, so these
alerts contain text and map links only.

### Windows one-command launcher

After installing Python dependencies and running `npm install` in `frontend`,
launch the broker, FastAPI backend, toy-model edge simulator, and dashboard in
four separate PowerShell windows:

```powershell
.\launch_demo.ps1
```

The launcher waits for Mosquitto on port `1883` before starting the other
components. To also open a fifth window for the optional WhatsApp gateway
(after installing its Node packages), use:

```powershell
.\launch_demo.ps1 -StartWhatsAppGateway
```

The launcher uses `.venv` when available, then `venv`, and otherwise a Python
found on `PATH`. It does not install dependencies automatically.

## Telemetry contract

Each event emitted by `edge_sim.py` follows this compact shape:

```json
{
  "bus_id": "BEST-104",
  "timestamp": 1726800000,
  "route_id": "R-12",
  "gps": [18.5204, 73.8567],
  "detection": {
    "class": "pothole_severe",
    "confidence": 0.94,
    "bbox": [120, 340, 280, 450]
  },
  "anpr": {
    "plate_number": null,
    "confidence": null
  },
  "network_status": "ONLINE",
  "payload_bytes": 250
}
```

`payload_bytes` is calculated from the compact JSON serialization. The edge
simulator verifies that normal events remain below the 1 KB ceiling.

## End-to-end demo checklist

Use four terminals:

| Terminal | Command | Expected result |
| --- | --- | --- |
| 1 | `docker compose up -d` | Mosquitto exposes 1883 and 9001 |
| 2 | `python server.py` | FastAPI starts on port 8000 and subscribes to telemetry |
| 3 | `python edge_sim.py --bus-id BEST-104 --route R-12` | Events are published or queued |
| 4 | `cd frontend; npm run dev` | Dashboard starts on port 5173 |

Then verify:

1. The edge terminal reports `connected=True`.
2. The backend terminal reports an MQTT subscription.
3. `/api/events` begins returning detection records.
4. The dashboard map and event cards update.
5. After approximately 10 seconds, nearby multi-bus events appear in the
   DBSCAN `clusters` table.
6. Stop the broker, allow the edge simulator to queue events, restart the
   broker, and confirm the queue flushes.

## Troubleshooting

### Docker is not recognized

Install Docker Desktop, start it, and reopen PowerShell. Check:

```powershell
docker version
docker compose version
```

### MQTT connection refused

Check the broker:

```powershell
docker compose ps
docker compose logs mosquitto
Test-NetConnection localhost -Port 1883
Test-NetConnection localhost -Port 9001
```

Ensure `server.py` and `edge_sim.py` use the same transport and port.

### Backend says `paho-mqtt is not installed`

Activate the project environment and install:

```powershell
python -m pip install paho-mqtt
```

### DBSCAN is disabled

Install the clustering dependencies:

```powershell
python -m pip install numpy scikit-learn
```

Restart `server.py` after installation.

### ONNX inference fails

Confirm all three packages are installed:

```powershell
python -m pip install opencv-python numpy onnxruntime
```

Also confirm that the model path exists and that the ONNX export matches the
input/output assumptions documented above. Without `--video` or `--model`, the
simulator intentionally uses synthetic detections.

### Dashboard cannot reach the API

Confirm that:

- `server.py` is running on port 8000.
- The browser can open `http://localhost:8000/api/stats`.
- Vite is running on port 5173.
- The backend CORS configuration still allows `http://localhost:5173`.

### Reset local demo state

Stop the services first, then remove only the generated local databases:

```powershell
Remove-Item .\database.db -ErrorAction SilentlyContinue
Remove-Item .\edge_queue.db -ErrorAction SilentlyContinue
docker compose down
```

`docker compose down -v` also removes Mosquitto's named persistence volumes
and should only be used when a completely clean broker state is desired.

## Privacy, safety, and limitations

- Use only footage, plate data, and recipient numbers that your team is
  authorized to process. Keep real camera footage and personally identifying
  data out of this repository.
- The included ONNX fixture emits static example detections. It is for
  integration testing only, not a validated YOLO model.
- The development Mosquitto setup allows anonymous access on local ports.
  Do not expose it to an untrusted network.
- WhatsApp dispatch is optional, sends real messages only when explicitly
  enabled, and is not required for the demo. Obtain recipient consent and
  verify the dry-run payload before sending.
- OpenStreetMap-based maps may request tiles from an external tile provider;
  the complete dashboard is not guaranteed to work offline without a local
  tile source.
- GPS, speed, network state, and IMU values are simulated by default.
- This is a hackathon prototype. Do not use it for emergency response,
  enforcement, or safety-critical decisions.

## GitHub collaboration

- See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution and data-handling
  guidance.
- CI runs the focused Python test suite and frontend lint/build for pushes and
  pull requests.
- Before publishing, confirm the repository owner, public/private visibility,
  and open-source license with the team.

## Stop the stack

In each foreground terminal, press `Ctrl+C`. Then stop Mosquitto:

```powershell
docker compose down
```

The Compose volumes preserve Mosquitto data across normal restarts.
