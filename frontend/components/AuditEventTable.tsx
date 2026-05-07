import type { AuditEvent } from "../lib/types";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);

function statusClass(event: AuditEvent) {
  if (["approved", "resolved", "false_positive"].includes(event.triage_status)) return "success";
  if (["acknowledged", "investigating"].includes(event.triage_status)) return "denied";
  if (event.signal_type === "action_required") return "failure";
  if (event.signal_type === "attention") return "denied";
  if (event.signal_type === "informational") return "success";
  if (event.impact_type === "destructive" || event.risk_level === "critical") return "failure";
  if (event.impact_type === "security_sensitive" || event.impact_type === "access_change" || event.is_denied) return "denied";
  if (event.impact_type === "constructive") return "success";
  const result = event.result.toLowerCase();
  if (event.is_denied || result.includes("denied")) return "denied";
  if (event.is_failure || result.includes("failure")) return "failure";
  if (result.includes("success")) return "success";
  return "neutral";
}

function impactLabel(event: AuditEvent) {
  if (event.triage_status && event.triage_status !== "open") {
    return event.triage_status.replace("_", " ");
  }
  return event.decision_label || "Info";
}

function displayResource(event: AuditEvent) {
  if (event.resource_display_name && event.resource_display_name !== "-") return event.resource_display_name;
  if (event.resource_name && event.resource_name !== "-") return event.resource_name;
  return event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
}

function displayActor(event: AuditEvent) {
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  if (display && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase())) return display;
  if (event.actor_email && event.actor_email !== display) return event.actor_email;
  if (raw) return raw;
  return "Unknown principal";
}

function actorSecondary(event: AuditEvent) {
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const email = event.actor_email || "";
  const primary = displayActor(event);
  if (email && raw && email !== raw && primary !== email && primary !== raw) return `${email} • ${raw}`;
  if (email && primary !== email) return email;
  return raw && raw !== primary ? raw : "";
}

function displaySourceIp(event: AuditEvent) {
  if (event.source_ip) return event.source_ip;
  if (event.source_context) return `No source IP / context: ${event.source_context}`;
  return "No source IP in audit event";
}

function displaySummary(event: AuditEvent) {
  const summary = event.event_summary || event.summary || "";
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const actor = displayActor(event);
  return raw && actor && raw !== actor ? summary.replace(raw, actor) : summary;
}

export default function AuditEventTable({ events, onSelect }: { events: AuditEvent[]; onSelect: (event: AuditEvent) => void }) {
  return (
    <div className="panel table-panel">
      <table className="event-table">
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
          {events.map((event) => (
            <tr key={event.id} onClick={() => onSelect(event)} className={`event-row signal-${event.signal_type}`}>
              <td className="nowrap">{new Date(event.timestamp).toLocaleString()}</td>
              <td>
                <span className={`status ${statusClass(event)}`}>{impactLabel(event)}</span>
                <span className="risk-label">{event.triage_status && event.triage_status !== "open" ? "triaged" : event.decision_reason || event.signal_reason}</span>
              </td>
              <td className="identity-cell" title={actorSecondary(event) || displayActor(event)}>
                <strong>{displayActor(event)}</strong>
                {actorSecondary(event) ? <span>{actorSecondary(event)}</span> : null}
              </td>
              <td className="summary-cell"><strong>{event.event_title || event.normalized_action}</strong><span>{displaySummary(event)}</span></td>
              <td className="resource-cell" title={event.resource_scope ? `${displayResource(event)}\n${event.resource_scope}` : displayResource(event)}>{displayResource(event)}</td>
              <td className="truncate-cell" title={displaySourceIp(event)}>{displaySourceIp(event)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
