import { Fragment } from "react";
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

function decisionReason(event: AuditEvent): string {
  const reason = (event.decision_reason || event.signal_reason || "").trim();
  if (!reason) return "";
  if (reason.length <= REASON_MAX_CHARS) return reason;
  return `${reason.slice(0, REASON_MAX_CHARS - 1).trimEnd()}…`;
}

function isServiceAccount(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function displayResource(event: AuditEvent) {
  if (event.resource_display_name && event.resource_display_name !== "-") return event.resource_display_name;
  if (event.resource_name && event.resource_name !== "-") return event.resource_name;
  return event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
}

type ActorDisplay = { primary: string; secondary: string; isServiceAccount: boolean; unenriched: boolean };

// True only when actor_display_name holds a real human-readable name —
// distinct from the raw id and not one of the Unknown* placeholders. Some
// events get persisted with display_name == raw_id when enrichment hasn't
// run yet (cache cold, missing creds, missing IAM record); we must treat
// those as unenriched so the cell renders in italic grey rather than
// pretending the raw id is a name.
function isEnrichedDisplay(display: string, raw: string): boolean {
  if (!display) return false;
  if (display === raw) return false;
  return !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase());
}

function displayActor(event: AuditEvent): ActorDisplay {
  const isSA = isServiceAccount(event);
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  const enriched = isEnrichedDisplay(display, raw);

  if (isSA) {
    const primary = enriched ? display : (raw || "Unknown service account");
    const secondary = enriched && raw && raw !== primary ? raw : "";
    return { primary, secondary, isServiceAccount: true, unenriched: !enriched };
  }
  // Human users: email is the most recognisable identifier — promote it.
  if (email) {
    const secondary = enriched && display !== email ? display : (raw && raw !== email ? raw : "");
    return { primary: email, secondary, isServiceAccount: false, unenriched: false };
  }
  // No email — use the enriched display only when it's actually a name.
  if (enriched) {
    return { primary: display, secondary: raw && raw !== display ? raw : "", isServiceAccount: false, unenriched: false };
  }
  return { primary: raw || "Unknown principal", secondary: "", isServiceAccount: false, unenriched: true };
}

// Best label for prose contexts (the plain-English sentence in the table).
// Prefers the human display name over the email — "Marcia Lima deleted X"
// reads more naturally than "mlima@confluent.io deleted X". The Who column
// uses a different priority (email first) because email is the more
// recognisable identifier when scanning a list of rows.
function bestSentenceLabel(event: AuditEvent): string {
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  if (isEnrichedDisplay(display, raw)) return display;
  if (email) return email;
  return raw || event.actor || "Unknown actor";
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

// "[actor] [verb] [resource] on [cluster] in [environment]" sentence built
// from action_category + action. Returns "" for Data / unmapped categories so
// the caller falls back to event_title (Data activity is dominated by
// automated reads that don't tell a useful story in the table).
function plainEnglishSummary(event: AuditEvent, resourceText: string): string {
  const cat = (event.action_category || "").trim();
  const action = (event.action || event.normalized_action || "").trim();
  const compact = action.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
  const cleanResource = resourceText && resourceText !== "Unknown" ? resourceText : "";
  const fallbackResource = cleanResource || "a resource";
  const actorLabel = bestSentenceLabel(event);

  let phrase = "";
  if (cat === "Delete") {
    phrase = `${actorLabel} deleted ${fallbackResource}`;
  } else if (cat === "Create") {
    phrase = `${actorLabel} created ${fallbackResource}`;
  } else if (cat === "Modify") {
    phrase = `${actorLabel} updated config on ${fallbackResource}`;
  } else if (cat === "Security") {
    if (compact.includes("revoke")) phrase = `${actorLabel} revoked access on ${fallbackResource}`;
    else if (compact.includes("grant") || compact.includes("bindrole")) phrase = `${actorLabel} granted access on ${fallbackResource}`;
    else if (compact.includes("createacl")) phrase = `${actorLabel} created ACL on ${fallbackResource}`;
    else if (compact.includes("deleteacl")) phrase = `${actorLabel} deleted ACL on ${fallbackResource}`;
    else phrase = `${actorLabel} changed access on ${fallbackResource}`;
  } else if (cat === "API Key") {
    const target = cleanResource ? ` for ${cleanResource}` : "";
    if (compact.includes("delete")) phrase = `${actorLabel} deleted API key${target}`;
    else if (compact.includes("create")) phrase = `${actorLabel} created API key${target}`;
    else if (compact.includes("rotate")) phrase = `${actorLabel} rotated API key${target}`;
    else if (compact.includes("update")) phrase = `${actorLabel} updated API key${target}`;
    else phrase = `${actorLabel} changed API key${target}`;
  } else {
    return "";
  }

  const cluster = (event.cluster_name || "").trim();
  const env = (event.environment_name || "").trim();
  if (cluster) phrase += ` on ${cluster}`;
  if (env) phrase += ` in ${env}`;
  return phrase;
}

function ExpandedEventRow({ event, detail, loading, error }: {
  event: AuditEvent;
  detail: AuditEvent | null;
  loading: boolean;
  error: string | null;
}) {
  const data = detail || event;
  const reason = (data.decision_reason || data.signal_reason || "").trim();
  const recommended = (data.recommended_action || "").trim();
  const resourceText = displayResource(data);
  return (
    <tr className="event-row-expanded">
      <td colSpan={6}>
        <div className="expanded-block">
          {loading ? <p className="muted">Loading details…</p> : null}
          {error ? <p className="panel-error">Could not load detail — {error}</p> : null}
          <div className="expanded-why">
            <strong>Why this matters:</strong> <span>{reason || data.decision_label || "Audit activity"}</span>
            {recommended ? <div className="expanded-recommended">→ Recommended: {recommended}</div> : null}
          </div>
          <div className="expanded-grid">
            <div><span className="muted">Resource:</span>{" "}<strong>{resourceText}</strong>{data.resource_type ? <span className="muted"> ({data.resource_type})</span> : null}</div>
            <div><span className="muted">Cluster:</span>{" "}<strong>{data.cluster_name || data.cluster_id || "—"}</strong>{"  "}<span className="muted">Environment:</span>{" "}<strong>{data.environment_name || data.environment_id || "—"}</strong></div>
            <div><span className="muted">Source IP:</span>{" "}<strong>{data.source_ip || "—"}</strong>{"  "}<span className="muted">Time:</span>{" "}<strong>{new Date(data.timestamp).toLocaleString()}</strong></div>
            <div><span className="muted">Triage:</span>{" "}<strong>{data.triage_status || "open"}</strong></div>
          </div>
          <details className="expanded-tech">
            <summary>Technical details ▸</summary>
            <div className="expanded-grid expanded-grid-tech">
              <div><span className="muted">Signal type:</span> {data.signal_type || "—"}</div>
              <div><span className="muted">Risk level:</span> {data.risk_level || "—"}</div>
              <div><span className="muted">Impact:</span> {data.impact_type || "—"}</div>
              <div><span className="muted">Resource family:</span> {data.resource_family || "—"}</div>
              <div><span className="muted">Resource scope:</span> {data.resource_scope || "—"}</div>
              <div><span className="muted">Actor source:</span> {data.actor_source || "—"} ({data.actor_confidence || "—"})</div>
              <div><span className="muted">Client ID:</span> {data.client_id || "—"}</div>
              <div><span className="muted">Request ID:</span> {data.request_id || "—"}</div>
              <div><span className="muted">Fingerprint:</span> <code>{data.event_fingerprint}</code></div>
            </div>
          </details>
        </div>
      </td>
    </tr>
  );
}

export default function AuditEventTable({ events, expandedId, expandedDetail, expandedLoading, expandedError, onToggleExpand }: {
  events: AuditEvent[];
  expandedId: number | null;
  expandedDetail: AuditEvent | null;
  expandedLoading: boolean;
  expandedError: string | null;
  onToggleExpand: (event: AuditEvent) => void;
}) {
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
            const resourceText = displayResource(event);
            const plainEng = plainEnglishSummary(event, resourceText);
            const isExpanded = expandedId === event.id;
            return (
              <Fragment key={event.id}>
                <tr onClick={() => onToggleExpand(event)} className={`event-row signal-${event.signal_type}${isExpanded ? " expanded" : ""}`}>
                  <td className="nowrap">{new Date(event.timestamp).toLocaleString()}</td>
                  <td className="decision-cell">
                    <span className={`status ${statusClass(event)}`}>{impactLabel(event)}</span>
                    {triaged ? (
                      <span className="decision-reason">triaged</span>
                    ) : reason ? (
                      <span className="decision-reason" title={event.decision_reason || event.signal_reason || ""}>{reason}</span>
                    ) : null}
                  </td>
                  <td className={`identity-cell${actor.unenriched ? " unenriched" : ""}`} title={actor.secondary || actor.primary}>
                    <strong>
                      {actor.primary}
                      {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
                    </strong>
                    {actor.secondary ? <span>{actor.secondary}</span> : null}
                  </td>
                  <td className="summary-cell">
                    {plainEng ? (
                      <strong>{plainEng}</strong>
                    ) : (
                      <>
                        <strong>{event.event_title || event.normalized_action}</strong>
                        <span>{displaySummary(event)}</span>
                      </>
                    )}
                  </td>
                  <td className="resource-cell" title={event.resource_scope ? `${resourceText}\n${event.resource_scope}` : resourceText}>{resourceText}</td>
                  <td className="truncate-cell" title={displaySourceIp(event)}>{displaySourceIp(event)}</td>
                </tr>
                {isExpanded ? (
                  <ExpandedEventRow
                    event={event}
                    detail={expandedDetail}
                    loading={expandedLoading}
                    error={expandedError}
                  />
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
