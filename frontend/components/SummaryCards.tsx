import type { SummaryResponse } from "../lib/types";

function topAction(summary: SummaryResponse) {
  const [action, count] = Object.entries(summary.by_action_category).sort((a, b) => b[1] - a[1])[0] || ["None", 0];
  return { action, count };
}

export default function SummaryCards({ summary, lastUpdated }: { summary: SummaryResponse; lastUpdated?: string }) {
  const top = topAction(summary);
  return (
    <div className="summary-strip">
      <div className="metric-card">
        <div className="metric-label">Total Events</div>
        <div className="metric-value">{summary.total_events.toLocaleString()}</div>
        <div className="metric-note">Current query window</div>
      </div>
      <div className="metric-card danger">
        <div className="metric-label">Failures</div>
        <div className="metric-value">{summary.failures.toLocaleString()}</div>
        <div className="metric-note">{summary.denials.toLocaleString()} denied</div>
      </div>
      <div className="metric-card accent">
        <div className="metric-label">Top Action</div>
        <div className="metric-value compact">{top.action}</div>
        <div className="metric-note">{top.count.toLocaleString()} events</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Last Updated</div>
        <div className="metric-value compact">{lastUpdated || "Just now"}</div>
        <div className="metric-note">Browser refresh time</div>
      </div>
    </div>
  );
}
