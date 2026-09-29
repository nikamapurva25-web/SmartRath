# SmartRath dashboard

React + Vite command dashboard for the SmartRath SIH26124 prototype by
HexaBytes. It renders bus telemetry, backend DBSCAN clusters, safety alerts,
and the daily origin-destination summary using MapLibre GL JS.

## Run locally

From the repository root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

The Vite development server normally listens on
`http://localhost:5173`. Start the FastAPI backend first at
`http://localhost:8000`; the dashboard uses its REST endpoints and WebSocket
feed.

## Validate a change

```powershell
npm --prefix frontend run lint
npm --prefix frontend run build
```

See the root [README](../README.md) for the complete local stack, MQTT
configuration, and demo launcher.
