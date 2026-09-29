function EventTable({ events = [] }) {
  return (
    <div className="event-table-card">

      <div className="table-header">

        <div>
          <h2>Detected Urban Events</h2>

          <p>
            AI-generated events from the transport fleet
          </p>
        </div>

        <span className="event-count">
          {events.length} Events
        </span>

      </div>

      <div className="table-container">

        <table>

          <thead>
            <tr>
              <th>Event ID</th>
              <th>Type</th>
              <th>Location</th>
              <th>Confidence</th>
              <th>Severity</th>
              <th>Status</th>
            </tr>
          </thead>

          <tbody>

            {events.map((event) => {
              const severity = event.event_type === "anpr_alert" || event.event_type === "congestion_bottleneck"
                ? "High"
                : event.members > 5 ? "High" : "Medium";
              const status = "Active";
              const location = event.location || `${Number(event.lat || 0).toFixed(4)}, ${Number(event.lng || 0).toFixed(4)}`;
              const confidence = event.confidence == null ? "—" : `${Math.round(Number(event.confidence) * (Number(event.confidence) <= 1 ? 100 : 1))}%`;
              return (
              <tr key={event.id}>
                <td>{event.id}</td>
                <td>{event.type || event.detection_class || event.event_type}</td>
                <td>{location}</td>
                <td>{confidence}</td>

                <td>
                  <span
                    className={`severity ${severity
                      .toLowerCase()
                      .replace(" ", "-")}`}
                  >
                    {severity}
                  </span>
                </td>

                <td>
                  <span
                    className={`status ${status
                      .toLowerCase()
                      .replace(" ", "-")}`}
                  >
                    {status}
                  </span>
                </td>
              </tr>
              );
            })}

          </tbody>

        </table>

      </div>

    </div>
  );
}

export default EventTable;