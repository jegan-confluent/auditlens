import type { SummaryResponse } from "../lib/types";

export default function SummaryCards({ summary }: { summary: SummaryResponse }) {
  return (
    <div className="grid">
      <div className="card"><div className="muted">Events</div><h2>{summary.total_events}</h2></div>
      <div className="card"><div className="muted">Failures</div><h2>{summary.failures}</h2></div>
      <div className="card"><div className="muted">Denials</div><h2>{summary.denials}</h2></div>
      <div className="card"><div className="muted">Create Events</div><h2>{summary.by_action_category.Create || 0}</h2></div>
    </div>
  );
}
