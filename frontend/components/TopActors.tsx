"use client";

import Link from "next/link";
import type { SummaryResponse } from "../lib/types";
import { normalizeActorDisplay } from "../lib/utils";

type ActorRow = {
  rawId: string;
  display: string;
  emoji: string;
  isSa: boolean;
  count: number;
  href: string | null;
};

function parseExternalAccount(value: string): string | null {
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const ea = parsed.externalAccount as Record<string, unknown> | undefined;
    if (typeof ea?.subject === "string" && ea.subject) return ea.subject;
  } catch {
    // ignore
  }
  return null;
}

function buildDisplayMap(summary: SummaryResponse): Map<string, string> {
  const map = new Map<string, string>();
  for (const g of summary.flow_groups ?? []) {
    if (g.subject && g.subject_display_name && !map.has(g.subject)) {
      map.set(g.subject, g.subject_display_name);
    }
  }
  return map;
}

function buildActorRows(
  summary: SummaryResponse,
  timeWindow: string,
): { rows: ActorRow[]; total: number } {
  const displayMap = buildDisplayMap(summary);
  const subjects = summary.top_subjects ?? [];

  const rows: ActorRow[] = subjects.map((s) => {
    const raw = s.value;

    // JSON blob — Confluent platform internal actor
    if (raw.startsWith("{") || raw.startsWith("[")) {
      const subject = parseExternalAccount(raw);
      const display = subject ?? "Confluent (platform)";
      const hrefId = subject ?? display;
      return {
        rawId: raw,
        display,
        emoji: "🏢",
        isSa: false,
        count: s.count,
        href: `/events?actor=${encodeURIComponent(hrefId)}&time_window=${timeWindow}`,
      };
    }

    const isSa = raw.startsWith("sa-");
    const isUser = raw.startsWith("u-");
    const fromMap = displayMap.get(raw);
    const display = fromMap ?? normalizeActorDisplay(raw);

    return {
      rawId: raw,
      display,
      emoji: isSa ? "🤖" : isUser ? "👤" : "",
      isSa,
      count: s.count,
      href: `/events?actor=${encodeURIComponent(raw)}&time_window=${timeWindow}`,
    };
  });

  return { rows: rows.slice(0, 5), total: subjects.length };
}

export default function TopActors({
  timeWindow = "24h",
  summary,
}: {
  timeWindow?: string;
  summary?: SummaryResponse | null;
}) {
  if (!summary) return null;

  const { rows, total } = buildActorRows(summary, timeWindow);

  if (!rows.length) {
    return (
      <section className="top-actors panel">
        <h2>Who was active — last {timeWindow}</h2>
        <p className="muted">No actor activity in this window.</p>
      </section>
    );
  }

  return (
    <section className="top-actors panel">
      <h2>Who was active — last {timeWindow}</h2>
      <ul className="top-actors-list">
        {rows.map((actor) => {
          const inner = (
            <>
              {actor.emoji ? <span className="top-actor-icon">{actor.emoji}</span> : null}
              <span className="top-actor-name">{actor.display}</span>
              {actor.isSa ? <span className="actor-badge sa" title="Service account">SA</span> : null}
              <span className="top-actor-count">
                {actor.count.toLocaleString()} event{actor.count === 1 ? "" : "s"}
              </span>
            </>
          );
          return (
            <li key={actor.rawId} className="top-actor-row">
              {actor.href ? <Link href={actor.href}>{inner}</Link> : <span>{inner}</span>}
            </li>
          );
        })}
        {total > 5 ? (
          <li className="top-actor-view-all">
            <Link href={`/events?time_window=${timeWindow}`}>View all {total} actors →</Link>
          </li>
        ) : null}
      </ul>
    </section>
  );
}
