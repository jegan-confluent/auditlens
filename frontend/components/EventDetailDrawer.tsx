"use client";

import type { AuditEvent } from "../lib/types";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);

function displayAction(event: AuditEvent) {
  return event.normalized_action || event.action_category || event.action || "Unknown";
}

function displayResource(event: AuditEvent) {
  return event.resource_name && event.resource_name !== "-" ? event.resource_name : event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
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
  if (email && raw && email !== raw && primary !== email && primary !== raw) return `${email} / ${raw}`;
  if (email && primary !== email) return email;
  return raw && raw !== primary ? raw : "";
}

function displaySummary(event: AuditEvent) {
  const summary = event.event_summary || event.summary || "";
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const actor = displayActor(event);
  return raw && actor && raw !== actor ? summary.replace(raw, actor) : summary;
}

function displaySource(event: AuditEvent) {
  if (event.source_ip) return event.source_ip;
  if (event.source_context) return `No source IP / context: ${event.source_context}`;
  return "No source IP in audit event";
}

function copyText(value: string) {
  if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
  navigator.clipboard.writeText(value).catch(() => undefined);
}

const triageActions = [
  { status: "acknowledged", label: "Acknowledge" },
  { status: "approved", label: "Mark Approved" },
  { status: "investigating", label: "Investigate" },
  { status: "resolved", label: "Resolve" },
  { status: "false_positive", label: "Mark False Positive" }
];

export default function EventDetailDrawer({ event, onClose, onTriage }: {
  event: AuditEvent | null;
  onClose: () => void;
  onTriage?: (status: string) => void;
}) {
  if (!event) return null;
  return (
    <aside className="drawer">
      <div className="drawer-header">
        <div>
          <div className="eyebrow">Audit event</div>
          <h2>{event.event_title || event.summary || "Audit event detail"}</h2>
          <p className="muted">{displaySummary(event)}</p>
        </div>
        <button onClick={onClose}>Close</button>
      </div>
      <div className="detail-grid">
        <div><div className="detail-label">Timestamp</div><strong>{new Date(event.timestamp).toLocaleString()}</strong></div>
        <div><div className="detail-label">Who</div><strong>{displayActor(event)}</strong>{actorSecondary(event) ? <span className="detail-secondary">{actorSecondary(event)}</span> : null}</div>
        <div><div className="detail-label">Actor Type</div><strong>{event.actor_type || event.subject_type || "unknown"}</strong></div>
        <div><div className="detail-label">Actor Source</div><strong>{event.actor_source || "fallback"}</strong>{event.actor_confidence ? <span className="detail-secondary">{event.actor_confidence} confidence</span> : null}</div>
        <div><div className="detail-label">Action</div><strong>{event.event_title || displayAction(event)}</strong></div>
        <div><div className="detail-label">Decision</div><strong>{event.decision_label}: {event.recommended_action}</strong></div>
        <div><div className="detail-label">Decision Reason</div><strong>{event.decision_reason || event.signal_reason}</strong></div>
        <div><div className="detail-label">Triage Status</div><strong>{event.triage_status || "open"}</strong>{event.triage_note ? <span className="detail-secondary">{event.triage_note}</span> : null}</div>
        <div><div className="detail-label">Risk Level</div><strong>{event.risk_level}</strong></div>
        <div><div className="detail-label">Impact Type</div><strong>{event.impact_type}</strong></div>
        <div><div className="detail-label">Change Type</div><strong>{event.change_type}</strong></div>
        <div><div className="detail-label">Resource Family</div><strong>{event.resource_family}</strong></div>
        <div><div className="detail-label">Result</div><strong>{event.result || "Unknown"}</strong></div>
        <div><div className="detail-label">Resource</div><strong>{displayResource(event)}</strong></div>
        <div><div className="detail-label">Resource Type</div><strong>{event.resource_type || "unknown"}</strong></div>
        <div><div className="detail-label">Environment</div><strong>{event.environment_id || "Not provided by audit event"}</strong></div>
        <div><div className="detail-label">Region</div><strong>{event.flink_region || "Not provided by audit event"}</strong></div>
        <div><div className="detail-label">Source IP</div><strong>{displaySource(event)}</strong></div>
        <div><div className="detail-label">Cluster</div><strong>{event.cluster_id || "Not provided by audit event"}</strong></div>
        <div><div className="detail-label">Client ID</div><strong>{event.client_id || "Not provided by audit event"}</strong></div>
        <div><div className="detail-label">Connection ID</div><strong>{event.connection_id || "Not provided by audit event"}</strong></div>
        <div><div className="detail-label">Request ID</div><strong>{event.request_id || "Not provided by audit event"}</strong></div>
      </div>
      <div className="triage-actions">
        {triageActions.map((action) => (
          <button key={action.status} onClick={() => onTriage?.(action.status)}>{action.label}</button>
        ))}
      </div>
      <div className="fingerprint-row">
        <div>
          <div className="detail-label">Fingerprint</div>
          <code>{event.event_fingerprint}</code>
        </div>
        <button onClick={() => copyText(event.event_fingerprint)}>Copy</button>
      </div>
      <details className="raw-payload">
        <summary>Raw payload</summary>
        <div className="raw-actions">
          <button onClick={() => copyText(event.raw_payload_json || "")}>Copy raw payload</button>
        </div>
        <pre>{event.raw_payload_json || "Raw payload is available only from the detail endpoint."}</pre>
      </details>
    </aside>
  );
}
