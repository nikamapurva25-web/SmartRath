import { useEffect, useState } from "react";
import { getDetections } from "../services/api";

function DetectionFeed() {
  const [detection, setDetection] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const loadDetection = async () => {
      try {
        setLoading(true);

        const data = await getDetections();

        setDetection(data);
        setError("");
      } catch (err) {
        console.error("Detection API error:", err);
        setError("Unable to load AI detection data.");
      } finally {
        setLoading(false);
      }
    };

    loadDetection();

    // Refresh detection data every 5 seconds
    const interval = setInterval(loadDetection, 5000);

    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="detection-feed">
        <h2>Live AI Detection</h2>
        <p>Loading AI detection...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="detection-feed">
        <h2>Live AI Detection</h2>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  const event = detection?.detections?.[0];

  return (
    <div className="detection-feed">

      <div className="feed-header">
        <div>
          <h2>Live AI Detection</h2>
          <p>AI analysis from existing fleet data</p>
        </div>

        <span className="live-status">
          ● LIVE
        </span>
      </div>

      <div className="camera-panel">

        {/* Simulated Camera */}
        <div className="camera-frame">

          <div className="camera-overlay">
            <span>
              BUS ROUTE {event?.route || "102"}
            </span>

            <span>
              CAM-{event?.route || "102"}
            </span>
          </div>

          <div className="detection-box">

            <span>
              {event?.type || "Detecting"}
            </span>

            <small>
              {event?.confidence || 0}% confidence
            </small>

          </div>

          <div className="camera-message">
            AI analyzing road scene...
          </div>

        </div>

        {/* Detection Details */}
        <div className="detection-details">

          <div>
            <span>Detected Event</span>
            <strong>
              {event?.type || "No detection"}
            </strong>
          </div>

          <div>
            <span>AI Model</span>
            <strong>
              {detection?.model || "YOLOv8"}
            </strong>
          </div>

          <div>
            <span>Confidence</span>
            <strong>
              {event?.confidence || 0}%
            </strong>
          </div>

          <div>
            <span>GPS Location</span>
            <strong>
              {event
                ? `${event.lat}, ${event.lng}`
                : "Unavailable"}
            </strong>
          </div>

          <div>
            <span>Timestamp</span>
            <strong>
              {event?.timestamp || "Unavailable"}
            </strong>
          </div>

          <div>
            <span>Status</span>
            <strong className="processing">
              {detection?.status || "Processing"}
            </strong>
          </div>

        </div>

      </div>

    </div>
  );
}

export default DetectionFeed;