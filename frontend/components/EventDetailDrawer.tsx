"use client";

import type { AuditEvent } from "../lib/types";
import SignalBadge from "./SignalBadge";

const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);

function resolveClientTool(tool: string | null | undefined): string | null {
  if (!tool || !tool.trim()) return null;
  const t = tool.trim();
  if (t === "unknown") return null;
  if (t.startsWith("confluent-") || t.startsWith("adminclient-")) return null;
  return t;
}
const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);
const STALE_EVENT_THRESHOLD_MS = 2 * 60 * 60 * 1000; // 2 hours

function displayAction(event: AuditEvent) {
  return event.normalized_action || event.action_category || event.action || "Unknown";
}

function displayResource(event: AuditEvent) {
  if (event.resource_display_name && event.resource_display_name !== "-") return event.resource_display_name;
  if (event.resource_name && event.resource_name !== "-") return event.resource_name;
  return event.resource_display_short || event.resource_display || event.resource_type || "Unknown";
}

function isServiceAccount(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function displayActor(event: AuditEvent): { primary: string; secondary: string; isServiceAccount: boolean } {
  const isSA = isServiceAccount(event);
  const display = (event.actor_display_name || event.subject || event.actor || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  const email = (event.actor_email || "").trim();
  if (isSA) {
    const primary = display && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase()) ? display : raw || "Unknown service account";
    const secondary = raw && raw !== primary ? raw : "";
    return { primary, secondary, isServiceAccount: true };
  }
  if (email) {
    const secondary = display && display !== email ? display : (raw && raw !== email ? raw : "");
    return { primary: email, secondary, isServiceAccount: false };
  }
  if (display && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase())) {
    return { primary: display, secondary: raw && raw !== display ? raw : "", isServiceAccount: false };
  }
  return { primary: raw || "Unknown principal", secondary: "", isServiceAccount: false };
}

function displaySummary(event: AuditEvent) {
  const summary = event.event_summary || event.summary || "";
  const raw = event.actor_raw_id || event.subject || event.actor || "";
  const { primary } = displayActor(event);
  return raw && primary && raw !== primary ? summary.replace(raw, primary) : summary;
}

function displaySource(event: AuditEvent) {
  if (event.source_ip && event.source_ip.trim()) return event.source_ip;
  return "—";
}

function displayContext(value?: string | null) {
  if (!value || value === "-") return "Not provided by audit event";
  return value;
}

function copyText(value: string) {
  if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
  navigator.clipboard.writeText(value).catch(() => undefined);
}

function eventAgeHours(event: AuditEvent): number | null {
  const ts = Date.parse(event.timestamp);
  if (Number.isNaN(ts)) return null;
  const ageMs = Date.now() - ts;
  if (ageMs < STALE_EVENT_THRESHOLD_MS) return null;
  return Math.round(ageMs / (60 * 60 * 1000));
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
  const actor = displayActor(event);
  const ageHours = eventAgeHours(event);
  const recommended = (event.recommended_action || "").trim();
  const reason = (event.decision_reason || event.signal_reason || "").trim();

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

      {ageHours !== null ? (
        <div className="drawer-stale-banner">
          ⚠️ This event is {ageHours} {ageHours === 1 ? "hour" : "hours"} old — forwarder may be behind real-time.
        </div>
      ) : null}

      {(event.signal_type === "action_required" || event.signal_type === "attention") ? (
        <section className="why-this-matters">
          <div className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            Why this matters
            {event.risk_level && event.risk_level !== "unknown" && event.risk_level !== "-" ? (
              <span style={{
                display: "inline-block",
                padding: "1px 7px",
                borderRadius: 4,
                fontSize: "0.7em",
                fontWeight: 700,
                letterSpacing: "0.04em",
                textTransform: "uppercase",
                color: "#fff",
                background: event.risk_level === "critical" ? "#b42318"
                  : event.risk_level === "high" ? "#b54708"
                  : event.risk_level === "medium" ? "#ca8a04"
                  : "#9ca3af",
              }}>{event.risk_level}</span>
            ) : null}
          </div>
          {(event.decision_label || reason) ? (
            <div style={{ marginBottom: 8 }}>
              <div className="detail-label">Decision</div>
              <strong>{event.decision_label || "Audit activity"}</strong>
              {reason ? <p style={{ margin: "2px 0 0" }}>{reason}</p> : null}
            </div>
          ) : null}
          {recommended ? (
            <div style={{ marginBottom: 8 }}>
              <div className="detail-label">What to do</div>
              <p style={{ margin: 0 }}>→ {recommended}</p>
            </div>
          ) : null}
          {(event.resource_criticality || event.blast_radius_hint || event.production_hint) ? (
            <div>
              <div className="detail-label">Resource context</div>
              {event.resource_criticality && event.resource_criticality !== "-" ? <p style={{ margin: "2px 0 0" }}>Criticality: {event.resource_criticality}</p> : null}
              {event.blast_radius_hint && event.blast_radius_hint !== "-" ? <p style={{ margin: "2px 0 0" }}>Blast radius: {event.blast_radius_hint}</p> : null}
              {event.production_hint && event.production_hint !== "-" ? <p style={{ margin: "2px 0 0" }}>Environment: {event.production_hint}</p> : null}
            </div>
          ) : null}
        </section>
      ) : (
        <section className="why-this-matters">
          <div className="eyebrow">Why this matters</div>
          <strong>{reason || event.decision_label || "Audit activity"}</strong>
          {recommended ? <p>→ Recommended: {recommended}</p> : null}
        </section>
      )}

      <div className="detail-grid">
        <div><div className="detail-label">Who</div><strong>{actor.primary}{actor.isServiceAccount ? <span className="actor-badge sa">SA</span> : null}</strong>{actor.secondary ? <span className="detail-secondary">{actor.secondary}</span> : null}{event.actor_confidence ? <span className="detail-secondary" title="Enrichment confidence">{event.actor_confidence} confidence</span> : null}{resolveClientTool(event.client_tool) ? <span className="detail-secondary">via {resolveClientTool(event.client_tool)}</span> : null}</div>
        <div><div className="detail-label">What</div><strong>{event.event_title || displayAction(event)}</strong></div>
        <div><div className="detail-label">Resource</div><strong>{displayResource(event)}</strong>{event.resource_type ? <span className="detail-secondary">{event.resource_type}</span> : null}</div>
        <div><div className="detail-label">When</div><strong>{new Date(event.timestamp).toLocaleString()}</strong></div>
        <div><div className="detail-label">Cluster</div><strong>{displayContext(event.cluster_name || event.cluster_id)}</strong></div>
        <div><div className="detail-label">Environment</div><strong>{displayContext(event.environment_name || event.environment_id)}</strong></div>
        <div><div className="detail-label">Source IP</div><strong>{displaySource(event)}</strong></div>
        <div><div className="detail-label">Result</div><strong>{event.result || "Unknown"}</strong></div>
        <div><div className="detail-label">Triage Status</div><strong>{event.triage_status || "open"}</strong>{event.triage_note ? <span className="detail-secondary">{event.triage_note}</span> : null}</div>
      </div>

      {event.action_category === "Security" && (event.rbac_role || event.rbac_scope) ? (
        <section className="why-this-matters" style={{ borderLeftColor: "#6366f1" }}>
          <div className="eyebrow">Access control</div>
          {event.rbac_role ? <div><div className="detail-label">RBAC Role</div><strong>{event.rbac_role}</strong></div> : null}
          {event.rbac_scope ? <div><div className="detail-label">RBAC Scope</div><strong>{event.rbac_scope}</strong></div> : null}
        </section>
      ) : null}

      <div className="triage-actions">
        {triageActions.map((action) => (
          <button key={action.status} onClick={() => onTriage?.(action.status)}>{action.label}</button>
        ))}
      </div>

      <details className="technical-details">
        <summary>Technical details</summary>
        <div className="detail-grid">
          <div><div className="detail-label">Signal Type</div><SignalBadge signal={event.signal_type} size="md" /></div>
          <div><div className="detail-label">Signal Reason</div><strong>{event.signal_reason || "—"}</strong></div>
          <div><div className="detail-label">Risk Level</div><strong>{event.risk_level || "—"}</strong></div>
          <div><div className="detail-label">Impact Type</div><strong>{event.impact_type || "—"}</strong></div>
          <div><div className="detail-label">Change Type</div><strong>{event.change_type || "—"}</strong></div>
          <div><div className="detail-label">Resource Family</div><strong>{event.resource_family || "—"}</strong></div>
          <div><div className="detail-label">Resource Scope</div><strong>{displayContext(event.resource_scope)}</strong></div>
          <div><div className="detail-label">Parent Resource</div><strong>{displayContext(event.parent_resource)}</strong></div>
          <div><div className="detail-label">Resource Criticality</div><strong>{displayContext(event.resource_criticality)}</strong></div>
          <div><div className="detail-label">Blast Radius</div><strong>{displayContext(event.blast_radius_hint)}</strong></div>
          <div><div className="detail-label">Production Hint</div><strong>{displayContext(event.production_hint)}</strong></div>
          <div><div className="detail-label">Region</div><strong>{event.flink_region || "—"}</strong></div>
          <div><div className="detail-label">Actor Type</div><strong>{event.actor_type || event.subject_type || "—"}</strong></div>
          <div><div className="detail-label">Actor Source</div><strong>{event.actor_source || "—"}</strong>{event.actor_confidence ? <span className="detail-secondary">{event.actor_confidence} confidence</span> : null}</div>
          <div><div className="detail-label">Actor Enriched At</div><strong>{event.actor_enriched_at || "—"}</strong></div>
          <div><div className="detail-label">Client ID</div><strong>{event.client_id || "—"}</strong></div>
          <div><div className="detail-label">Connection ID</div><strong>{event.connection_id || "—"}</strong></div>
          <div><div className="detail-label">Request ID</div><strong>{event.request_id || "—"}</strong></div>
        </div>
      </details>

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
