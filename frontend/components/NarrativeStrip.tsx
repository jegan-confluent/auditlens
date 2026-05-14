"use client";

import Link from "next/link";
import type { SummaryResponse } from "../lib/types";

function resolveTopActor(summary: SummaryResponse): { display: string; count: number } | null {
  const group = summary.flow_groups?.[0];
  if (!group) return null;
  const raw = group.subject_display_name || group.subject || "";
  if (!raw || raw.startsWith("{")) return null;
  const display = raw.startsWith("User:") ? raw.slice(5)
    : raw.startsWith("ServiceAccount:") ? raw.slice(15)
    : raw;
  return { display, count: group.event_count };
}

export default function NarrativeStrip({
  summary,
  timeWindow = "24h",
}: {
  summary: SummaryResponse;
  timeWindow?: string;
}) {
  const actionRequired = summary.action_required_count ?? 0;
  const attention = summary.attention_count ?? 0;
  const failures = summary.failure_count ?? 0;
  const topActor = resolveTopActor(summary);

  return (
    <div className="narrative-strip">
      {actionRequired > 0 ? (
        <Link
          href={`/events?signal=action_required&time_window=${timeWindow}`}
          className="narrative-line narrative-line-critical"
        >
          ⚠ {actionRequired} event{actionRequired === 1 ? "" : "s"} need action
          {topActor
            ? ` — ${topActor.display} is most active with ${topActor.count.toLocaleString()} changes in the last ${timeWindow}.`
            : "."}
        </Link>
      ) : attention > 0 ? (
        <span className="narrative-line narrative-line-ok">
          ✓ No critical events — {attention.toLocaleString()} event{attention === 1 ? "" : "s"} under review in the last {timeWindow}.
        </span>
      ) : (
        <span className="narrative-line narrative-line-ok">
          ✓ All clear in the last {timeWindow}.
        </span>
      )}
      {failures > 0 ? (
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
