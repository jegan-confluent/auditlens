import type { SummaryResponse } from "../lib/types";

function topAction(summary: SummaryResponse) {
  const [action, count] = Object.entries(summary.by_action_category).sort((a, b) => b[1] - a[1])[0] || ["None", 0];
  return { action, count };
}

function dataAsOf(newestEvent: string | null | undefined): { label: string; note: string } {
  if (!newestEvent) {
    return { label: "No recent data", note: "Forwarder may not have produced any events yet" };
  }
  const ts = Date.parse(newestEvent);
  if (Number.isNaN(ts)) {
    return { label: "No recent data", note: "Could not parse newest event timestamp" };
  }
  const ageMinutes = Math.max(0, Math.floor((Date.now() - ts) / 60000));
  const note =
    ageMinutes < 5
      ? "Up to date"
      : ageMinutes < 60
        ? `${ageMinutes} min behind real-time`
        : `${Math.round(ageMinutes / 60)} h behind real-time`;
  return { label: `Data as of ${new Date(ts).toLocaleTimeString()}`, note };
}

export default function SummaryCards({ summary, newestEvent }: { summary: SummaryResponse; newestEvent?: string | null }) {
  const top = topAction(summary);
  const freshness = dataAsOf(newestEvent);
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
        <div className="metric-label">Data Freshness</div>
        <div className="metric-value compact">{freshness.label}</div>
        <div className="metric-note">{freshness.note}</div>
      </div>
    </div>
  );
}
