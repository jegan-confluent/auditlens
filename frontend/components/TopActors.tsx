"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEvents, isAbortError } from "../lib/api";
import type { AuditEvent, EventListResponse } from "../lib/types";

const SERVICE_ACCOUNT_TYPES = new Set(["service_account", "serviceaccount", "service-account"]);
const UNKNOWN_PRINCIPAL_LABELS = new Set(["unknown actor", "unknown user", "unknown service account", "unknown principal"]);

type ActorSummary = {
  key: string;        // raw id, used for filter param
  display: string;    // primary label shown to user
  rawId: string;
  email: string;
  unenriched: boolean;
  isServiceAccount: boolean;
  count: number;
  topCategories: string[];
  hasDeletes: boolean;
};

function isServiceAccount(event: AuditEvent): boolean {
  const type = (event.actor_type || event.subject_type || "").toLowerCase();
  if (SERVICE_ACCOUNT_TYPES.has(type)) return true;
  const raw = (event.actor_raw_id || event.actor || "").toLowerCase();
  return raw.startsWith("sa-") || raw.startsWith("user:sa-");
}

function rawIdOf(event: AuditEvent): string {
  return (event.actor_raw_id || event.subject || event.actor || "").trim();
}

function aggregate(events: AuditEvent[], limit = 5): ActorSummary[] {
  const buckets = new Map<string, {
    rawId: string;
    display: string;
    email: string;
    isSA: boolean;
    unenriched: boolean;
    count: number;
    categories: Map<string, number>;
    hasDeletes: boolean;
  }>();
  for (const event of events) {
    const raw = rawIdOf(event);
    const key = raw || event.actor || "unknown";
    const display = (event.actor_display_name || "").trim();
    const email = (event.actor_email || "").trim();
    const isSA = isServiceAccount(event);
    const enriched = Boolean(display && display !== raw && !UNKNOWN_PRINCIPAL_LABELS.has(display.toLowerCase()));
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        rawId: raw,
        display: enriched ? display : (email || raw || "unknown"),
        email,
        isSA,
        unenriched: !enriched && !email,
        count: 1,
        categories: new Map([[event.action_category || "Other", 1]]),
        hasDeletes: event.action_category === "Delete"
      });
      continue;
    }
    existing.count += 1;
    const cat = event.action_category || "Other";
    existing.categories.set(cat, (existing.categories.get(cat) || 0) + 1);
    if (cat === "Delete") existing.hasDeletes = true;
    // Promote a richer label if a later event provides one (some events are
    // enriched, others aren't; pick the best one we've seen).
    if (enriched && (existing.unenriched || !existing.display.includes(display))) {
      existing.display = display;
      existing.unenriched = false;
    } else if (!existing.email && email) {
      existing.email = email;
      if (existing.unenriched) {
        existing.display = email;
        existing.unenriched = false;
      }
    }
  }
  return [...buckets.entries()]
    .map(([key, info]) => {
      const topCats = [...info.categories.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 2)
        .map(([cat]) => cat);
      return {
        key,
        display: info.display,
        rawId: info.rawId,
        email: info.email,
        unenriched: info.unenriched,
        isServiceAccount: info.isSA,
        count: info.count,
        topCategories: topCats,
        hasDeletes: info.hasDeletes
      };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

export default function TopActors({ timeWindow = "24h" }: { timeWindow?: string }) {
  const [actors, setActors] = useState<ActorSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanned, setScanned] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      time_window: timeWindow,
      mode: "audit_trail",
      limit: "500"
    });
    getEvents(params, controller.signal)
      .then((response: EventListResponse) => {
        setScanned(response.items.length);
        setActors(aggregate(response.items));
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message);
      });
    return () => controller.abort();
  }, [timeWindow]);

  if (error) {
    return (
      <section className="top-actors panel">
        <h2>Top actors today</h2>
        <p className="panel-error">Could not load top actors — {error}</p>
      </section>
    );
  }
  if (!actors) {
    return (
      <section className="top-actors panel">
        <h2>Top actors today</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }
  if (!actors.length) {
    return (
      <section className="top-actors panel">
        <h2>Top actors today</h2>
        <p className="muted">No actor activity in the last 24 hours.</p>
      </section>
    );
  }

  return (
    <section className="top-actors panel">
      <h2>Top actors today</h2>
      <p className="muted">Most active principals in the last 24 hours (sample of {scanned.toLocaleString()} events).</p>
      <ul className="top-actors-list">
        {actors.map((actor) => {
          const filterValue = actor.rawId || actor.key;
          const href = `/events?actor=${encodeURIComponent(filterValue)}&time_window=${timeWindow}`;
          const mostly = actor.topCategories.length ? `mostly: ${actor.topCategories.join(", ")}` : "";
          return (
            <li key={actor.key} className={`top-actor-row${actor.hasDeletes ? " has-deletes" : ""}`}>
              <Link href={href}>
                <span className="top-actor-icon">{actor.isServiceAccount ? "🤖" : "👤"}</span>
                <span className={`top-actor-name${actor.unenriched ? " unenriched" : ""}`}>{actor.display}</span>
                {actor.isServiceAccount ? <span className="actor-badge sa" title="Service account">SA</span> : null}
                <span className="top-actor-count">{actor.count.toLocaleString()} event{actor.count === 1 ? "" : "s"}</span>
                {mostly ? <span className="top-actor-mostly">{mostly}</span> : null}
                {actor.hasDeletes ? <span className="top-actor-flag" title="Performed delete operations today">⚠ has deletes</span> : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
