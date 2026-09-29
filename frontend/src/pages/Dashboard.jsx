import { useEffect, useState } from "react";

import Navbar from "../components/Navbar";
import StatsCard from "../components/StatsCard";
import EventMap from "../maps/EventMap";
import DetectionFeed from "../components/DetectionFeed";
import EventTable from "../components/EventTable";
import Analytics from "../components/Analytics";
import { getEvents, getOdMatrix, getStats } from "../services/api";

const API_HOST = "127.0.0.1:8000";
const TRAIL_LIMIT = 40;

function Dashboard() {
  const [events, setEvents] = useState([]);
  const [buses, setBuses] = useState([]);
  const [trails, setTrails] = useState({});
  const [stats, setStats] = useState(null);
  const [odMatrix, setOdMatrix] = useState(null);
  const [activeLayer, setActiveLayer] = useState("infrastructure");
  const [connection, setConnection] = useState("CONNECTING");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const loadInitialData = async () => {
      try {
        const [eventData, statsData, matrixData] = await Promise.all([
          getEvents(),
          getStats(),
          getOdMatrix(),
        ]);
        if (cancelled) return;
        setEvents(eventData.events || []);
        setBuses(eventData.buses || []);
        setStats(statsData);
        setOdMatrix(matrixData);
        setError("");
      } catch (loadError) {
        console.error("Dashboard API error:", loadError);
        if (!cancelled) setError("Unable to connect to the backend API.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    loadInitialData();
    const odRefresh = window.setInterval(async () => {
      try {
        setOdMatrix(await getOdMatrix());
      } catch (refreshError) {
        console.error("O-D matrix refresh failed:", refreshError);
      }
    }, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(odRefresh);
    };
  }, []);

  useEffect(() => {
    let socket;
    let reconnectTimer;
    let disposed = false;
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(`ws://${API_HOST}/ws`);
      socket.onopen = () => setConnection("ONLINE");
      socket.onmessage = (message) => {
        let update;
        try {
          update = JSON.parse(message.data);
        } catch (parseError) {
          console.error("Invalid WebSocket update:", parseError);
          return;
        }
        if (update.type === "telemetry" && update.event) {
          const point = update.event;
          setBuses((current) => {
            const next = current.filter((bus) => bus.bus_id !== point.bus_id);
            return [...next, {
              bus_id: point.bus_id,
              route_id: point.route_id,
              lat: point.lat,
              lng: point.lng,
              timestamp: point.timestamp,
              speed_kmh: point.speed_kmh,
              baseline_speed_kmh: point.baseline_speed_kmh,
              vehicle_count: point.vehicle_count,
            }];
          });
          setTrails((current) => {
            const points = [...(current[point.bus_id] || []), point].slice(-TRAIL_LIMIT);
            return { ...current, [point.bus_id]: points };
          });
          if (point.type === "pedestrian_risk") {
            const safetyEvent = {
              ...point,
              id: `risk-${point.bus_id}-${point.timestamp}`,
              event_type: "safety_risk",
            };
            setEvents((current) => [safetyEvent, ...current].slice(0, 200));
          }
        }
        if (update.type === "congestion_bottleneck" && update.event) {
          const event = update.event;
          setEvents((current) => [
            { ...event, id: `congestion-${event.bus_id}-${event.timestamp}` },
            ...current.filter((item) => item.event_type !== "congestion_bottleneck"),
          ].slice(0, 200));
        }
        if (update.type === "anpr_alert" && update.event) {
          const event = update.event;
          setEvents((current) => [
            { ...event, id: `anpr-${event.bus_id}-${event.timestamp}` },
            ...current,
          ].slice(0, 200));
        }
        if (update.type === "clusters_update") {
          const clusters = (update.clusters || []).map((cluster) => ({
            ...cluster,
            id: `${cluster.event_type}-${cluster.cluster_id}`,
            type: cluster.detection_class,
          }));
          setEvents((current) => [
            ...current.filter((event) => event.event_type === "anpr_alert" || event.event_type === "safety_risk"),
            ...clusters,
          ]);
        }
      };
      socket.onclose = () => {
        setConnection("OFFLINE");
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return (
    <div>
      <Navbar />
      <main className="dashboard">
        <header className="dashboard-heading">
          <div>
            <p className="eyebrow">HEXABYTES · SIH26124</p>
            <h1>SmartRath City Operations</h1>
            <p>Edge intelligence for safer roads, better transit, and responsive cities.</p>
          </div>
          <div className={`connection-badge ${connection.toLowerCase()}`}>
            <span className="connection-dot" />
            LIVE BUS LINK · {connection}
          </div>
        </header>

        {loading && <p className="loading-message">Loading urban intelligence data...</p>}
        {error && <p className="error-message">{error}</p>}

        {!loading && !error && stats && (
          <>
            <div className="stats-container">
              <StatsCard title="Telemetry Events" value={stats.total_events} />
              <StatsCard title="Critical Potholes" value={stats.critical_issues} />
              <StatsCard title="Routes Monitored" value={stats.routes_monitored} />
              <StatsCard title="AI Confidence" value={`${stats.ai_confidence}%`} />
            </div>

            <section className="map-section">
              <div className="map-heading">
                <div>
                  <h2>SmartRath Operations Map</h2>
                  <p>Live bus position, deduplicated hazards, and conditional safety alerts</p>
                </div>
                <div className="layer-control" role="tablist" aria-label="Map layers">
                  {[
                    ["infrastructure", "Infrastructure"],
                    ["traffic", "Traffic"],
                    ["safety", "Safety"],
                  ].map(([layer, label]) => (
                    <button
                      key={layer}
                      type="button"
                      role="tab"
                      aria-selected={activeLayer === layer}
                      className={activeLayer === layer ? "active" : ""}
                      onClick={() => setActiveLayer(layer)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <EventMap events={events} buses={buses} trails={trails} activeLayer={activeLayer} />
              <div className="map-legend">
                {activeLayer === "infrastructure" && <span><i className="legend-dot hazard" /> DBSCAN hazard heatmap</span>}
                {activeLayer === "traffic" && <><span><i className="legend-dot normal" /> At / above route baseline</span><span><i className="legend-dot bottleneck" /> Below 60% baseline</span></>}
                {activeLayer === "safety" && <span className="safety-legend"><i className="legend-dot bottleneck" /> IMU-triggered ANPR / safety alert</span>}
                <span>{buses.length} buses reporting</span>
              </div>
            </section>

            <section className="od-panel">
              <div>
                <h2>Daily Origin–Destination Summary</h2>
                <p>{odMatrix?.date || "Waiting for today's GPS aggregates"} · generated from local telemetry</p>
              </div>
              <strong>{odMatrix?.matrix?.length || 0} route flows</strong>
            </section>

            <div className="detection-section"><DetectionFeed /></div>
            <div className="events-section"><EventTable events={events} /></div>
            <div className="analytics-wrapper"><Analytics events={events} /></div>
          </>
        )}
      </main>
    </div>
  );
}

export default Dashboard;
