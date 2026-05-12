import Link from "next/link";
import type { SummaryResponse } from "../lib/types";

function resolveTopActorDisplay(summary: SummaryResponse): { display: string; rawId: string; count: number } | null {
  const group = summary.flow_groups?.[0];
  if (!group) return null;
  return {
    display: group.subject_display_name || group.subject,
    rawId: group.subject,
    count: group.event_count,
  };
}

function resolveDestructiveActor(summary: SummaryResponse): string | null {
  const group = summary.flow_groups?.find((g) => g.impact_type === "destructive");
  if (!group) return null;
  return group.subject_display_name || group.subject || null;
}

export default function NarrativeStrip({
  summary,
  timeWindow = "24h",
}: {
  summary: SummaryResponse;
  timeWindow?: string;
}) {
  const actionRequired = summary.action_required_count ?? 0;
  const destructive = summary.destructive_count ?? 0;
  const failures = summary.failure_count ?? 0;
  const topActor = resolveTopActorDisplay(summary);
  const destructiveActor = destructive > 0 ? resolveDestructiveActor(summary) : null;

  return (
    <div className="narrative-strip">
      {/* Line 1 — status headline */}
      {actionRequired > 0 ? (
        <Link
          href={`/events?signal=action_required&time_window=${timeWindow}`}
          className="narrative-line narrative-line-critical"
        >
          🔴 {actionRequired} event{actionRequired === 1 ? "" : "s"} need immediate attention.
        </Link>
      ) : (
        <span className="narrative-line narrative-line-ok">
          ✅ Nothing critical in the last {timeWindow}.
        </span>
      )}

      {/* Line 2 — top actor */}
      {topActor ? (
        <span className="narrative-line narrative-line-primary">
          {topActor.count.toLocaleString()} events from{" "}
          <Link
            href={`/events?actor=${encodeURIComponent(topActor.rawId)}&time_window=${timeWindow}`}
            className="narrative-actor-link"
          >
            {topActor.display}
          </Link>{" "}
          led activity.
        </span>
      ) : null}

      {/* Line 3 — destructive or failures (conditional) */}
      {destructive > 0 ? (
        <Link
          href={`/events?action_category=Delete&signal=action_required&time_window=${timeWindow}`}
          className="narrative-line narrative-line-warning"
        >
          {destructive} destructive action{destructive === 1 ? "" : "s"}
          {destructiveActor ? ` — ${destructiveActor}` : ""}.
        </Link>
      ) : failures > 0 ? (
        <Link
          href={`/events?result=Failure&time_window=${timeWindow}`}
          className="narrative-line narrative-line-secondary"
        >
          {failures.toLocaleString()} access failure{failures === 1 ? "" : "s"} recorded.
        </Link>
      ) : null}
    </div>
  );
}
