"use client";

import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

type CountField =
  | "failure_count"
  | "denied_count"
  | "destructive_count"
  | "configuration_change_count"
  | "access_change_count";

function derivePatch(field: CountField): Partial<EventFilters> {
  switch (field) {
    case "failure_count": return { result: "Failure" };
    case "denied_count": return { result: "Denied" };
    case "destructive_count": return { impact_type: "destructive" };
    case "configuration_change_count": return { impact_type: "configuration_change" };
    case "access_change_count": return { impact_type: "access_change" };
  }
}

function ClickableCount({ value, field, onApply }: {
  value: number | undefined;
  field: CountField;
  onApply?: (patch: Partial<EventFilters>) => void;
}) {
  const n = value ?? 0;
  return (
    <button
      type="button"
      className={`count-link${n === 0 ? " zero" : ""}`}
      onClick={() => onApply?.(derivePatch(field))}
    >
      {n.toLocaleString()}
    </button>
  );
}

function MessageContent({ summary, windowLabel, onApply }: {
  summary: SummaryResponse;
  windowLabel: string;
  onApply?: (patch: Partial<EventFilters>) => void;
}) {
  if (summary.overall_status === "action_required") {
    return (
      <>
        <ClickableCount value={summary.failure_count} field="failure_count" onApply={onApply} />{" "}failures,{" "}
        <ClickableCount value={summary.denied_count} field="denied_count" onApply={onApply} />{" "}denied attempts, and{" "}
        <ClickableCount value={summary.destructive_count} field="destructive_count" onApply={onApply} />{" "}destructive actions in the {windowLabel}.
      </>
    );
  }
  if (summary.overall_status === "review_needed") {
    return (
      <>
        <ClickableCount value={summary.configuration_change_count} field="configuration_change_count" onApply={onApply} />{" "}configuration changes and{" "}
        <ClickableCount value={summary.access_change_count} field="access_change_count" onApply={onApply} />{" "}access changes in the {windowLabel} need review.
      </>
    );
  }
  return (
    <>{summary.short_digest || `Most activity in the ${windowLabel} is routine authentication, authorization, or read-only access. No destructive, failed, or configuration-changing activity was detected.`}</>
  );
}

function titleFor(summary: SummaryResponse): string {
  if (summary.overall_status === "action_required") return "Critical activity detected — action required";
  if (summary.overall_status === "review_needed") return "Changes detected — review required";
  return "No action needed";
}

function actionFor(summary: SummaryResponse): string {
  if (summary.overall_status === "action_required") return "Investigate immediately and confirm owner, source IP, and affected resource.";
  if (summary.overall_status === "review_needed") return "Verify whether these changes match an approved change window.";
  return "Continue monitoring.";
}

function ctaFor(summary: SummaryResponse): { label: string; patch: Partial<EventFilters> } {
  if (summary.overall_status === "action_required") {
    return { label: "Investigate critical events", patch: { mode: "decision", signal: "action_required", hide_noise: "true" } };
  }
  if (summary.overall_status === "review_needed") {
    return { label: "Show changes to review", patch: { mode: "decision", signal: "attention", hide_noise: "true" } };
  }
  return { label: "Show full audit trail", patch: { mode: "audit_trail", time_window: "72h", signal: "", hide_noise: "false" } };
}

export default function DecisionBanner({ summary, timeWindowLabel, onApplyDecision }: {
  summary: SummaryResponse;
  timeWindowLabel: string;
  onApplyDecision?: (patch: Partial<EventFilters>) => void;
}) {
  const cta = ctaFor(summary);
  return (
    <section className={`decision-banner ${summary.overall_status}`}>
      <div>
        <div className="eyebrow">Decision</div>
        <h2>{titleFor(summary)}</h2>
        <p>
          <MessageContent summary={summary} windowLabel={timeWindowLabel} onApply={onApplyDecision} />
        </p>
        {summary.summary_scope === "sampled" ? (
          <span>{summary.sample_warning || `Based on latest ${summary.scanned_events.toLocaleString()} of ${summary.total_events.toLocaleString()} matching events.`}</span>
        ) : null}
      </div>
      <div className="decision-action">
        <strong>{actionFor(summary)}</strong>
        {onApplyDecision ? <button onClick={() => onApplyDecision(cta.patch)}>{cta.label}</button> : null}
      </div>
    </section>
  );
}
