import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

type NarrativeItem = {
  label: string;
  count: number;
  meaning: string;
  action: string;
  tone: string;
  filterPatch: Partial<EventFilters>;
};

function itemsFor(summary: SummaryResponse): NarrativeItem[] {
  const items: NarrativeItem[] = [];
  if (summary.destructive_count) {
    items.push({ label: "Destructive actions", count: summary.destructive_count, meaning: "Resources were deleted or removed.", action: "Confirm approval and blast radius.", tone: "critical", filterPatch: { impact_type: "destructive" } });
  }
  if (summary.configuration_change_count) {
    items.push({ label: "Configuration changes", count: summary.configuration_change_count, meaning: "Runtime or resource configuration changed.", action: "Verify expected change window.", tone: "review", filterPatch: { impact_type: "configuration_change" } });
  }
  if (summary.access_change_count) {
    items.push({ label: "Access changes", count: summary.access_change_count, meaning: "Identity, key, ACL, or role access changed.", action: "Confirm owner and approval.", tone: "review", filterPatch: { impact_type: "access_change" } });
  }
  const failedOrDenied = Math.max(summary.failure_count || 0, summary.denied_count || 0);
  if (failedOrDenied) {
    items.push({ label: "Failures / denied access", count: failedOrDenied, meaning: "Requests failed or were denied.", action: "Investigate actor, source, and resource.", tone: "critical", filterPatch: { result: "Failure" } });
  }
  if (summary.noise_count) {
    items.push({ label: "Routine noise", count: summary.noise_count, meaning: "Successful auth/authz checks and routine access.", action: "Hidden by default; show noise if needed.", tone: "muted", filterPatch: { signal: "noise", mode: "audit_trail", hide_noise: "false" } });
  }
  return items.slice(0, 5);
}

export default function NarrativeStrip({ summary, onApplyFilter }: {
  summary: SummaryResponse;
  onApplyFilter?: (patch: Partial<EventFilters>) => void;
}) {
  const items = itemsFor(summary);
  if (!items.length) {
    return (
      <section className="narrative-strip">
        <div className="narrative-item muted">
          <strong>Nothing changed</strong>
          <span>Activity is mostly routine access checks.</span>
          <em>Continue monitoring.</em>
        </div>
      </section>
    );
  }

  return (
    <section className="narrative-strip">
      {items.map((item) => {
        if (onApplyFilter) {
          return (
            <button
              key={item.label}
              type="button"
              className={`narrative-item ${item.tone}`}
              onClick={() => onApplyFilter(item.filterPatch)}
            >
              <strong>{item.count.toLocaleString()} {item.label}</strong>
              <span>{item.meaning}</span>
              <em>{item.action}</em>
            </button>
          );
        }
        return (
          <div key={item.label} className={`narrative-item ${item.tone}`}>
            <strong>{item.count.toLocaleString()} {item.label}</strong>
            <span>{item.meaning}</span>
            <em>{item.action}</em>
          </div>
        );
      })}
    </section>
  );
}
