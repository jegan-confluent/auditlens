import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

function countFor(summary: SummaryResponse, key: "noise_count" | "informational_count" | "attention_count" | "action_required_count") {
  return (summary[key] || 0).toLocaleString();
}

function resourceTypeForFamily(family: string) {
  const mapping: Record<string, string> = {
    topic: "Topic",
    connector: "Connector",
    schema_registry: "Schema Registry",
    api_key: "API Key",
    acl: "ACL / RBAC",
    rbac: "ACL / RBAC",
    cluster: "Cluster",
    flink: "Compute Pool"
  };
  return mapping[family] || "";
}

function flowPatch(group: SummaryResponse["flow_groups"][number]): Partial<EventFilters> {
  return {
    actor: group.subject || "",
    signal: group.signal_type || "",
    resource_type: resourceTypeForFamily(group.resource_family),
    resource: group.resource_display_short && group.resource_display_short !== "Unknown" ? group.resource_display_short : "",
    hide_noise: group.signal_type === "noise" ? "false" : "true"
  };
}

function filterPreview(patch: Partial<EventFilters>) {
  return [
    patch.actor ? `Actor: ${patch.actor}` : "",
    patch.signal ? `Signal: ${patch.signal}` : "",
    patch.resource ? `Resource: ${patch.resource}` : ""
  ].filter(Boolean);
}

export default function SignalSummaryPanel({ summary, onApplyFlow }: {
  summary: SummaryResponse;
  onApplyFlow?: (patch: Partial<EventFilters>) => void;
}) {
  const matters =
    summary.action_required_count > 0
      ? `${summary.action_required_count.toLocaleString()} action required`
      : summary.attention_count > 0
        ? `${summary.attention_count.toLocaleString()} items need review`
        : "No action needed";

  return (
    <section className={`signal-panel ${summary.overall_status}`}>
      <div className="signal-headline">
        <div>
          <div className="eyebrow">What matters</div>
          <h2>{matters}</h2>
          <p>{summary.headline}</p>
        </div>
        <div className="signal-digest">
          {summary.short_digest}
          {summary.summary_scope === "sampled" ? <span>{summary.sample_warning || `Summary based on latest ${summary.scanned_events.toLocaleString()} matching events.`}</span> : null}
        </div>
      </div>
      <div className="signal-counts">
        <div><span>Noise</span><strong>{countFor(summary, "noise_count")}</strong></div>
        <div><span>Info</span><strong>{countFor(summary, "informational_count")}</strong></div>
        <div><span>Review</span><strong>{countFor(summary, "attention_count")}</strong></div>
        <div><span>Action Needed</span><strong>{countFor(summary, "action_required_count")}</strong></div>
      </div>
      {summary.flow_groups.length ? (
        <div className="flow-list">
          <div className="eyebrow">Top activity flows</div>
          {summary.flow_groups.slice(0, 5).map((group) => {
            const patch = flowPatch(group);
            const preview = filterPreview(patch);
            const clickable = Boolean(onApplyFlow && (patch.actor || patch.signal || patch.resource_type || patch.resource));
            return (
              <div key={`${group.group_title}-${group.first_seen}`} className={`flow-card ${group.signal_type}`}>
                <strong>{group.group_title}</strong>
                <span>{group.group_summary}</span>
                <span>{group.event_count.toLocaleString()} events • {new Date(group.first_seen).toLocaleString()} - {new Date(group.last_seen).toLocaleString()}</span>
                <span>{group.subject} • {group.resource_family}{group.resource_display_short && group.resource_display_short !== "Unknown" ? ` • ${group.resource_display_short}` : ""}</span>
                {preview.length ? <span className="filter-preview">{preview.join(" • ")}</span> : null}
                <em>{group.recommended_action}</em>
                {clickable ? <button onClick={() => onApplyFlow?.(patch)}>Filter by this activity</button> : <span>Open details only</span>}
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
