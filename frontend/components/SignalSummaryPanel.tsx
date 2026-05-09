import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

function resourceTypeForFamily(family: string) {
  // Mirrors src/product/resource_intelligence.RESOURCE_TYPE_ALIASES (the
  // canonical types the forwarder emits after the 2026-05-08 alias
  // extension). When `flowPatch` produces a `resource_type` query value the
  // backend filter expects the string to round-trip canonically.
  const mapping: Record<string, string> = {
    topic: "Topic",
    subject: "Subject",
    connector: "Connector",
    schema_registry: "Schema Registry",
    api_key: "API Key",
    acl: "ACL / RBAC",
    rbac: "ACL / RBAC",
    role_binding: "ACL / RBAC",
    cluster: "Cluster",
    environment: "Environment",
    organization: "Organization",
    user: "User",
    service_account: "Service Account",
    ksql: "KSQLDB",
    ksqldb: "KSQLDB",
    flink: "Compute Pool",
    compute_pool: "Compute Pool",
    workspace: "Workspace",
    statement: "Statement",
    tableflow: "Tableflow",
    network: "Network",
    private_link: "Private Link",
    transit_gateway: "Transit Gateway",
    identity_pool: "Identity Pool",
    identity_provider: "Identity Provider",
    custom_connector_plugin: "Custom Connector Plugin",
    byok_key: "BYOK Key",
    sso_connection: "SSO Connection",
    mfa: "MFA",
    notification: "Notification",
    ai: "AI",
    lineage: "Stream Lineage",
    billing: "Billing",
    audit: "Audit"
  };
  return mapping[family] || "";
}

function flowPatch(group: SummaryResponse["flow_groups"][number]): Partial<EventFilters> {
  return {
    mode: group.signal_type === "noise" ? "audit_trail" : "decision",
    actor: group.subject || "",
    signal: group.signal_type || "",
    resource_type: resourceTypeForFamily(group.resource_family),
    resource: group.resource_display_short && group.resource_display_short !== "Unknown" ? group.resource_display_short : "",
    hide_noise: group.signal_type === "noise" ? "false" : "true"
  };
}

function statPatch(signal: string): Partial<EventFilters> {
  return { mode: signal === "noise" ? "audit_trail" : "decision", signal, hide_noise: signal === "noise" ? "false" : "true" };
}

function iconForSignal(signal: string): string {
  if (signal === "action_required") return "🔴";
  if (signal === "attention") return "🟡";
  if (signal === "informational") return "ℹ️";
  return "·";
}

function formatAge(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "recently";
  const ageMin = Math.max(0, (Date.now() - ts) / 60000);
  if (ageMin < 1) return "just now";
  if (ageMin < 60) return `${Math.round(ageMin)}m ago`;
  const ageH = ageMin / 60;
  if (ageH < 24) return `${Math.round(ageH * 10) / 10}h ago`;
  return `${Math.round(ageH / 24)}d ago`;
}

export default function SignalSummaryPanel({ summary, onApplyFlow }: {
  summary: SummaryResponse;
  onApplyFlow?: (patch: Partial<EventFilters>) => void;
}) {
  return (
    <section className={`signal-panel ${summary.overall_status}`}>
      <div className="signal-stat-cards">
        <button
          type="button"
          className="signal-stat-card noise"
          onClick={() => onApplyFlow?.(statPatch("noise"))}
        >
          <span className="signal-stat-icon" aria-hidden>🔇</span>
          <span className="signal-stat-count">{summary.noise_count.toLocaleString()}</span>
          <span className="signal-stat-label">Noise</span>
        </button>
        <button
          type="button"
          className="signal-stat-card info"
          onClick={() => onApplyFlow?.(statPatch("informational"))}
        >
          <span className="signal-stat-icon" aria-hidden>ℹ️</span>
          <span className="signal-stat-count">{summary.informational_count.toLocaleString()}</span>
          <span className="signal-stat-label">Info</span>
        </button>
        <button
          type="button"
          className={`signal-stat-card review ${summary.attention_count > 0 ? "amber" : ""}`}
          onClick={() => onApplyFlow?.(statPatch("attention"))}
        >
          <span className="signal-stat-icon" aria-hidden>👀</span>
          <span className="signal-stat-count">{summary.attention_count.toLocaleString()}</span>
          <span className="signal-stat-label">Review</span>
        </button>
        <button
          type="button"
          className={`signal-stat-card action ${summary.action_required_count > 0 ? "red" : ""}`}
          onClick={() => onApplyFlow?.(statPatch("action_required"))}
        >
          <span className="signal-stat-icon" aria-hidden>🔴</span>
          <span className="signal-stat-count">{summary.action_required_count.toLocaleString()}</span>
          <span className="signal-stat-label">Action</span>
        </button>
      </div>
      {summary.flow_groups.length ? (
        <div className="flow-list">
          <div className="eyebrow">Top activity flows</div>
          {summary.flow_groups.slice(0, 5).map((group) => {
            const patch = flowPatch(group);
            const clickable = Boolean(onApplyFlow && (patch.actor || patch.signal || patch.resource_type || patch.resource));
            const signalClass = group.signal_type === "action_required" ? "action_required" : group.signal_type === "attention" ? "attention" : "informational";
            const ButtonOrDiv = clickable ? "button" : "div";
            return (
              <ButtonOrDiv
                key={`${group.group_title}-${group.first_seen}`}
                type={clickable ? "button" : undefined}
                className={`flow-row ${signalClass}`}
                onClick={clickable ? () => onApplyFlow?.(patch) : undefined}
              >
                <span className="flow-icon" aria-hidden>{iconForSignal(group.signal_type)}</span>
                <span className="flow-body">
                  <span className="flow-title">{group.group_title}</span>
                  <span className="flow-meta">
                    {group.subject || "—"} · {formatAge(group.last_seen)}
                    {group.event_count > 1 ? ` · ${group.event_count.toLocaleString()} events` : ""}
                  </span>
                </span>
                <span className="flow-arrow" aria-hidden>{clickable ? "→" : ""}</span>
              </ButtonOrDiv>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
