import type { SummaryResponse } from "../lib/types";

type NarrativeItem = {
  label: string;
  count: number;
  meaning: string;
  action: string;
  tone: string;
};

function itemsFor(summary: SummaryResponse): NarrativeItem[] {
  const items: NarrativeItem[] = [];
  if (summary.destructive_count) {
    items.push({ label: "Destructive actions", count: summary.destructive_count, meaning: "Resources were deleted or removed.", action: "Confirm approval and blast radius.", tone: "critical" });
  }
  if (summary.configuration_change_count) {
    items.push({ label: "Configuration changes", count: summary.configuration_change_count, meaning: "Runtime or resource configuration changed.", action: "Verify expected change window.", tone: "review" });
  }
  if (summary.access_change_count) {
    items.push({ label: "Access changes", count: summary.access_change_count, meaning: "Identity, key, ACL, or role access changed.", action: "Confirm owner and approval.", tone: "review" });
  }
  const failedOrDenied = Math.max(summary.failure_count || 0, summary.denied_count || 0);
  if (failedOrDenied) {
    items.push({ label: "Failures / denied access", count: failedOrDenied, meaning: "Requests failed or were denied.", action: "Investigate actor, source, and resource.", tone: "critical" });
  }
  if (summary.noise_count) {
    items.push({ label: "Routine noise", count: summary.noise_count, meaning: "Successful auth/authz checks and routine access.", action: "Hidden by default; show noise if needed.", tone: "muted" });
  }
  return items.slice(0, 5);
}

export default function NarrativeStrip({ summary }: { summary: SummaryResponse }) {
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
      {items.map((item) => (
        <div key={item.label} className={`narrative-item ${item.tone}`}>
          <strong>{item.count.toLocaleString()} {item.label}</strong>
          <span>{item.meaning}</span>
          <em>{item.action}</em>
        </div>
      ))}
    </section>
  );
}
