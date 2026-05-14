"use client";

import Link from "next/link";
import type { SummaryResponse } from "../lib/types";

function resolveTopActor(summary: SummaryResponse): { display: string; count: number } | null {
  const groups = summary.flow_groups ?? [];
  const byActor = new Map<string, { display: string; count: number }>();
  for (const g of groups.filter(g => g.signal_type === "action_required")) {
    const existing = byActor.get(g.subject);
    const display = g.subject_display_name || g.subject || "";
    if (!existing) {
      byActor.set(g.subject, { display, count: g.event_count });
    } else {
      existing.count += g.event_count;
    }
  }
  const top = [...byActor.values()].sort((a, b) => b.count - a.count)[0];
  if (!top || !top.display || top.display.startsWith("{")) return null;
  const d = top.display.startsWith("User:") ? top.display.slice(5)
    : top.display.startsWith("ServiceAccount:") ? top.display.slice(15)
    : top.display;
  return { display: d, count: top.count };
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
