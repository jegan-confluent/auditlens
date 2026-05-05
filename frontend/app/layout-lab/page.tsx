import type React from "react";

const mockEvents = [
  { time: "10:28", decision: "Action Needed", who: "u-75rw9o", action: "Topic deleted", resource: "jegan-testing", source: "10.10.0.11" },
  { time: "10:24", decision: "Review", who: "sa-prod-admin", action: "Connector config updated", resource: "payment-sink", source: "lkc-prod" },
  { time: "10:18", decision: "Info", who: "u-reader", action: "Workspace listed", resource: "env-prod", source: "Confluent Cloud" }
];

const flows = [
  "Topic lifecycle activity for jegan-testing",
  "3 config changes by sa-prod-admin on payment-sink",
  "68 routine authorization checks by u-6zon76"
];

function MiniTable() {
  return (
    <div className="panel table-panel">
      <table className="event-table lab-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Decision</th>
            <th>Who</th>
            <th>What happened</th>
            <th>Resource</th>
            <th>Source/IP</th>
          </tr>
        </thead>
        <tbody>
          {mockEvents.map((event) => (
            <tr key={`${event.time}-${event.action}`}>
              <td>{event.time}</td>
              <td><span className={`status ${event.decision === "Action Needed" ? "failure" : event.decision === "Review" ? "denied" : "success"}`}>{event.decision}</span></td>
              <td>{event.who}</td>
              <td>{event.action}</td>
              <td>{event.resource}</td>
              <td>{event.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LabBadge({ children }: { children: React.ReactNode }) {
  return <span className="lab-badge">{children}</span>;
}

export default function LayoutLabPage() {
  return (
    <main className="page layout-lab">
      <div className="lab-intro">
        <div>
          <div className="eyebrow">Visual playground</div>
          <h1>AuditLens layout lab</h1>
          <p className="muted">Static mockups for comparing decision-first audit investigation layouts. Not production behavior.</p>
        </div>
        <div className="filter-chips">
          <LabBadge>Latest mode</LabBadge>
          <LabBadge>Noise hidden</LabBadge>
          <LabBadge>Sampled summary</LabBadge>
          <LabBadge>Backend filtered</LabBadge>
        </div>
      </div>

      <section className="lab-layout">
        <div className="lab-layout-header">
          <span className="eyebrow">Layout A</span>
          <h2>Operator Console</h2>
          <p>On-call friendly: puts the decision, next action, and freshest changes above the table.</p>
        </div>
        <div className="decision-banner action_required">
          <div>
            <div className="eyebrow">Decision</div>
            <h2>Action required</h2>
            <p>Topic deletion and failed access attempts were detected in the latest two-hour window.</p>
            <span>Sampled summary: latest 5,000 matching events. Filters: Latest mode, Noise hidden.</span>
          </div>
          <div className="decision-action">
            <strong>Recommended action</strong>
            <p>Confirm owner, source IP, and approval for the topic delete.</p>
            <button>Investigate critical events</button>
          </div>
        </div>
        <div className="lab-grid-three">
          <div className="card"><span className="metric-label">What just happened</span><strong>Topic deleted 4 minutes ago</strong><p className="muted">jegan-testing by u-75rw9o</p></div>
          <div className="card"><span className="metric-label">Top actor</span><strong>u-75rw9o</strong><p className="muted">2 destructive or failed events</p></div>
          <div className="card"><span className="metric-label">Top resource</span><strong>jegan-testing</strong><p className="muted">Topic lifecycle activity</p></div>
        </div>
        <MiniTable />
      </section>

      <section className="lab-layout">
        <div className="lab-layout-header">
          <span className="eyebrow">Layout B</span>
          <h2>Investigation Timeline</h2>
          <p>Debugging flow: emphasizes sequence, grouped activity, actor/resource context, and structured drill-down.</p>
        </div>
        <div className="lab-timeline-shell">
          <div className="panel lab-timeline">
            <div className="eyebrow">Latest activity timeline</div>
            {mockEvents.map((event) => (
              <div key={`timeline-${event.time}`} className="lab-timeline-row">
                <strong>{event.time}</strong>
                <span>{event.action}</span>
                <em>{event.who} on {event.resource}</em>
              </div>
            ))}
          </div>
          <div className="panel">
            <div className="eyebrow">Grouped event flows</div>
            {flows.map((flow) => <div className="flow-card" key={flow}><strong>{flow}</strong><span>Filter by this activity</span></div>)}
          </div>
          <aside className="panel lab-side-panel">
            <div className="eyebrow">Actor/resource context</div>
            <h3>u-75rw9o</h3>
            <p>Most recent critical action affected topic <strong>jegan-testing</strong>.</p>
            <div className="raw-preview">
              <strong>Raw event drawer preview</strong>
              <span>Structured fields first. Raw payload collapsed by default.</span>
            </div>
          </aside>
        </div>
      </section>

      <section className="lab-layout">
        <div className="lab-layout-header">
          <span className="eyebrow">Layout C</span>
          <h2>Executive Audit Summary</h2>
          <p>Customer-facing view: concise risk posture, coverage caveat, top changes, and drill-down CTA.</p>
        </div>
        <div className="summary-strip">
          <div className="metric-card danger"><span className="metric-label">Risk posture</span><div className="metric-value compact">Review required</div><p className="metric-note">1 destructive change detected</p></div>
          <div className="metric-card"><span className="metric-label">Coverage</span><div className="metric-value">5,000</div><p className="metric-note">Latest matching events sampled</p></div>
          <div className="metric-card accent"><span className="metric-label">Top change</span><div className="metric-value compact">Topic delete</div><p className="metric-note">jegan-testing</p></div>
          <div className="metric-card"><span className="metric-label">Noise hidden</span><div className="metric-value">Yes</div><p className="metric-note">Routine auth/authz suppressed</p></div>
        </div>
        <div className="panel compliance-summary">
          <h3>Compliance-friendly summary</h3>
          <p>AuditLens detected a destructive topic operation in the latest mode window. The action should be reconciled against the approved change record and resource owner.</p>
          <button>Drill into matching events</button>
        </div>
      </section>
    </main>
  );
}
