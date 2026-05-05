import type { SummaryResponse } from "../lib/types";
import type { EventFilters } from "../lib/eventFilters";

function titleFor(summary: SummaryResponse) {
  if (summary.overall_status === "action_required") return "Critical activity detected — action required";
  if (summary.overall_status === "review_needed") return "Changes detected — review required";
  return "No action needed";
}

function messageFor(summary: SummaryResponse) {
  if (summary.overall_status === "action_required") {
    return `${summary.failure_count.toLocaleString()} failures, ${summary.denied_count.toLocaleString()} denied attempts, and ${summary.destructive_count.toLocaleString()} destructive actions were found in the scanned window.`;
  }
  if (summary.overall_status === "review_needed") {
    return `${summary.configuration_change_count.toLocaleString()} configuration changes and ${summary.access_change_count.toLocaleString()} access changes need review.`;
  }
  return summary.short_digest || "Most activity is routine authentication, authorization, or read-only access. No destructive, failed, or configuration-changing activity was detected in the scanned window.";
}

function actionFor(summary: SummaryResponse) {
  if (summary.overall_status === "action_required") return "Investigate immediately and confirm owner, source IP, and affected resource.";
  if (summary.overall_status === "review_needed") return "Verify whether these changes match an approved change window.";
  return "Continue monitoring.";
}

function ctaFor(summary: SummaryResponse) {
  if (summary.overall_status === "action_required") {
    const patch: Partial<EventFilters> = { mode: "decision", signal: "action_required", hide_noise: "true" };
    return { label: "Investigate critical events", patch };
  }
  if (summary.overall_status === "review_needed") {
    const patch: Partial<EventFilters> = { mode: "decision", signal: "attention", hide_noise: "true" };
    return { label: "Show changes to review", patch };
  }
  const patch: Partial<EventFilters> = { mode: "audit_trail", time_window: "72h", signal: "", hide_noise: "false" };
  return { label: "Show full audit trail", patch };
}

export default function DecisionBanner({ summary, onApplyDecision }: {
  summary: SummaryResponse;
  onApplyDecision?: (patch: Partial<EventFilters>) => void;
}) {
  const cta = ctaFor(summary);
  return (
    <section className={`decision-banner ${summary.overall_status}`}>
      <div>
        <div className="eyebrow">Decision</div>
        <h2>{titleFor(summary)}</h2>
        <p>{messageFor(summary)}</p>
        {summary.summary_scope === "sampled" ? <span>{summary.sample_warning || `Based on latest ${summary.scanned_events.toLocaleString()} of ${summary.total_events.toLocaleString()} matching events.`}</span> : null}
      </div>
      <div className="decision-action">
        <strong>{actionFor(summary)}</strong>
        {onApplyDecision ? <button onClick={() => onApplyDecision(cta.patch)}>{cta.label}</button> : null}
      </div>
    </section>
  );
}
