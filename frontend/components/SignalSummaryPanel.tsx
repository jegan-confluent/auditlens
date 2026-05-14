import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

type SignalCountField = "noise_count" | "informational_count" | "attention_count" | "action_required_count";

function signalFromField(fieldKey: SignalCountField): string {
  return fieldKey.replace(/_count$/, "");
}

const SIGNAL_CARDS: ReadonlyArray<{
  fieldKey: SignalCountField;
  className: string;
  icon: string;
  label: string;
  contextLabel: string;
  alertClass?: (count: number) => string;
}> = [
  { fieldKey: "noise_count", className: "noise", icon: "🔇", label: "Noise", contextLabel: "all clear" },
  { fieldKey: "informational_count", className: "info", icon: "ℹ️", label: "Info", contextLabel: "informational" },
  { fieldKey: "attention_count", className: "review", icon: "👀", label: "Review", contextLabel: "monitored", alertClass: (c) => c > 0 ? "amber" : "" },
  { fieldKey: "action_required_count", className: "action", icon: "🔴", label: "Action", contextLabel: "needs review", alertClass: (c) => c > 0 ? "red" : "" },
];

type ActorFlow = {
  subject: string;
  subject_display_name: string | null | undefined;
  signal_type: string;
  count: number;
  last_seen: string;
};

function groupFlowsByActor(groups: SummaryResponse["flow_groups"]): ActorFlow[] {
  const map = new Map<string, ActorFlow>();
  for (const g of groups) {
    const key = `${g.subject}|${g.signal_type}`;
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        subject: g.subject,
        subject_display_name: g.subject_display_name,
        signal_type: g.signal_type,
        count: g.event_count,
        last_seen: g.last_seen,
      });
    } else {
      existing.count += g.event_count;
      if (g.last_seen > existing.last_seen) existing.last_seen = g.last_seen;
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

function actorSignalPatch(subject: string, signalType: string): Partial<EventFilters> {
  return {
    mode: signalType === "noise" ? "audit_trail" : "decision",
    actor: subject || "",
    signal: signalType || "",
    hide_noise: signalType === "noise" ? "false" : "true",
  };
}

function signalEventLabel(signalType: string): string {
  if (signalType === "action_required") return "action-needed";
  if (signalType === "attention") return "review-needed";
  if (signalType === "noise") return "routine";
  return "informational";
}

function resourceTypeForFamily(family: string): string {
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

function looksLikeJson(v: string): boolean {
  return v.startsWith("{") || v.startsWith("[");
}

function stripActorPrefix(subject: string): string {
  if (subject.startsWith("User:")) return subject.slice(5);
  if (subject.startsWith("ServiceAccount:")) return subject.slice(15);
  return subject;
}

function formatSubject(subject: string, displayName?: string | null): string {
  if (!subject) return "—";
  if (looksLikeJson(subject)) return "Confluent (platform)";
  if (displayName) return displayName;
  return stripActorPrefix(subject);
}

export default function SignalSummaryPanel({ summary, onApplyFlow, currentSignal }: {
  summary: SummaryResponse;
  onApplyFlow?: (patch: Partial<EventFilters>) => void;
  currentSignal?: string;
}) {
  const actorFlows = groupFlowsByActor(summary.flow_groups);
  return (
    <section className={`signal-panel ${summary.overall_status}`}>
      <div className="signal-stat-cards">
        {SIGNAL_CARDS.map(({ fieldKey, className, icon, label, contextLabel, alertClass }) => {
          const signalType = signalFromField(fieldKey);
          const count = summary[fieldKey];
          const isActive = currentSignal === signalType;
          const alertCls = alertClass ? alertClass(count) : "";
          const cardClass = [
            "signal-stat-card",
            className,
            alertCls,
            isActive ? "active" : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              key={fieldKey}
              type="button"
              className={cardClass}
              aria-pressed={isActive}
              onClick={() => onApplyFlow?.(isActive ? { signal: "" } : statPatch(signalType))}
            >
              <span className="signal-stat-icon" aria-hidden>{icon}</span>
              <span className="signal-stat-count">{count.toLocaleString()}</span>
              <span className="signal-stat-label">{label}</span>
              <span className="signal-stat-context">{contextLabel}</span>
            </button>
          );
        })}
      </div>
      {actorFlows.length ? (
        <div className="flow-list">
          <div className="eyebrow">Top activity flows</div>
          {actorFlows.slice(0, 5).map((flow) => {
            const patch = actorSignalPatch(flow.subject, flow.signal_type);
            const display = formatSubject(flow.subject, flow.subject_display_name);
            const evtLabel = signalEventLabel(flow.signal_type);
            const clickable = Boolean(onApplyFlow && (patch.actor || patch.signal));
            const signalClass = flow.signal_type === "action_required" ? "action_required"
              : flow.signal_type === "attention" ? "attention"
              : "informational";
            const ButtonOrDiv = clickable ? "button" : "div";
            return (
              <ButtonOrDiv
                key={`${flow.subject}|${flow.signal_type}`}
                type={clickable ? "button" : undefined}
                className={`flow-row ${signalClass}`}
                onClick={clickable ? () => onApplyFlow?.(patch) : undefined}
              >
                <span className="flow-icon" aria-hidden>{iconForSignal(flow.signal_type)}</span>
                <span className="flow-body">
                  <span className="flow-title">
                    {display} — {flow.count.toLocaleString()} {evtLabel} event{flow.count === 1 ? "" : "s"}
                  </span>
                  <span className="flow-meta">{formatAge(flow.last_seen)}</span>
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
