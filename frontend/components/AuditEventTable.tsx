import type { AuditEvent } from "../lib/types";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);
const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);
const REASON_MAX_CHARS = 60;

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

// Promote decision_reason to a visible second line under the badge so the
// "why" stops being a 12 px grey subline. Falls back to signal_reason if
// decision_reason is missing.
function decisionReason(event: AuditEvent): string {
  const reason = (event.decision_reason || event.signal_reason || "").trim();
  if (!reason) return "";
  if (reason.length <= REASON_MAX_CHARS) return reason;
  return `${reason.slice(0, REASON_MAX_CHARS - 1).trimEnd()}…`;
}

function isServiceAccount(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  // Fallback: "sa-" prefix on the raw id is a reliable signal in Confluent
  // Cloud even when actor_type wasn't enriched.
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function displayResource(event: AuditEvent) {
  if (event.resource_display_name && event.resource_display_name !== "-") return event.resource_display_name;
  if (event.resource_name && event.resource_name !== "-") return event.resource_name;
  return event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
}

function displayActor(event: AuditEvent): { primary: string; secondary: string; isServiceAccount: boolean } {
  const isSA = isServiceAccount(event);
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();

  // Service accounts: friendly display name primary, raw id secondary, SA badge.
  if (isSA) {
    const primary = display && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase()) ? display : raw || "Unknown service account";
    const secondary = raw && raw !== primary ? raw : "";
    return { primary, secondary, isServiceAccount: true };
  }
  // Human users: email is the most recognisable identifier — promote it.
  if (email) {
    const secondary = display && display !== email ? display : (raw && raw !== email ? raw : "");
    return { primary: email, secondary, isServiceAccount: false };
  }
  // No email — fall back to display, then raw.
  if (display && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase())) {
    return { primary: display, secondary: raw && raw !== display ? raw : "", isServiceAccount: false };
  }
  return { primary: raw || "Unknown principal", secondary: "", isServiceAccount: false };
}

function displaySourceIp(event: AuditEvent) {
  if (event.source_ip) return event.source_ip;
  if (event.source_context) return `No source IP / context: ${event.source_context}`;
  return "No source IP in audit event";
}

function displaySummary(event: AuditEvent) {
  const summary = event.event_summary || event.summary || "";
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const { primary } = displayActor(event);
  return raw && primary && raw !== primary ? summary.replace(raw, primary) : summary;
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
          {events.map((event) => {
            const actor = displayActor(event);
            const reason = decisionReason(event);
            const triaged = event.triage_status && event.triage_status !== "open";
            return (
              <tr key={event.id} onClick={() => onSelect(event)} className={`event-row signal-${event.signal_type}`}>
                <td className="nowrap">{new Date(event.timestamp).toLocaleString()}</td>
                <td className="decision-cell">
                  <span className={`status ${statusClass(event)}`}>{impactLabel(event)}</span>
                  {triaged ? (
                    <span className="decision-reason">triaged</span>
                  ) : reason ? (
                    <span className="decision-reason" title={event.decision_reason || event.signal_reason || ""}>{reason}</span>
                  ) : null}
                </td>
                <td className="identity-cell" title={actor.secondary || actor.primary}>
                  <strong>
                    {actor.primary}
                    {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
                  </strong>
                  {actor.secondary ? <span>{actor.secondary}</span> : null}
                </td>
                <td className="summary-cell"><strong>{event.event_title || event.normalized_action}</strong><span>{displaySummary(event)}</span></td>
                <td className="resource-cell" title={event.resource_scope ? `${displayResource(event)}\n${event.resource_scope}` : displayResource(event)}>{displayResource(event)}</td>
                <td className="truncate-cell" title={displaySourceIp(event)}>{displaySourceIp(event)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
