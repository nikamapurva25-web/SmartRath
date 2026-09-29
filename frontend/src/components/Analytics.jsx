import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const eventDistribution = [
  { name: "Potholes", value: 45 },
  { name: "Traffic Issues", value: 52 },
  { name: "Road Damage", value: 27 },
];

const routeIssues = [
  { route: "Route 101", issues: 28 },
  { route: "Route 102", issues: 41 },
  { route: "Route 103", issues: 32 },
  { route: "Route 104", issues: 23 },
];

const detectionTrend = [
  { time: "08:00", events: 8 },
  { time: "09:00", events: 14 },
  { time: "10:00", events: 22 },
  { time: "11:00", events: 17 },
  { time: "12:00", events: 26 },
  { time: "13:00", events: 19 },
];

function Analytics() {
  return (
    <div className="analytics-section">

      <div className="analytics-header">
        <h2>Urban Event Analytics</h2>
        <p>AI-generated event statistics</p>
      </div>

      <div className="analytics-grid">

        {/* Event Distribution */}
        <div className="chart-card">
          <h3>Event Distribution</h3>

          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={eventDistribution}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label
              >
                {eventDistribution.map((entry, index) => (
                  <Cell key={`cell-${index}`} />
                ))}
              </Pie>

              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Route-wise Issues */}
        <div className="chart-card">
          <h3>Route-wise Issues</h3>

          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={routeIssues}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="route" />
              <YAxis />
              <Tooltip />

              <Bar
                dataKey="issues"
                name="Detected Issues"
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Detection Trend */}
        <div className="chart-card full-width">
          <h3>Detection Trend</h3>

          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={detectionTrend}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" />
              <YAxis />
              <Tooltip />

              <Line
                type="monotone"
                dataKey="events"
                name="Detected Events"
                strokeWidth={3}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

      </div>

    </div>
  );
}

export default Analytics;