"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEvents, isAbortError } from "../lib/api";
import type { AuditEvent, EventListResponse } from "../lib/types";

type FeedGroup = {
  action: string;
  count: number;
  lastActor: string;
  lastAt: string;
};

type FeedCategory = {
  key: string;
  label: string;
  emoji: string;
  emptyMessage: string;
  href: string;
  fetchParams: URLSearchParams;
};

type FeedState = {
  status: "loading" | "loaded" | "error";
  groups: FeedGroup[];
  total: number;
  error: string | null;
};

const CATEGORIES: FeedCategory[] = [
  {
    key: "deletes",
    label: "Deletes",
    emoji: "🔴",
    emptyMessage: "No destructive deletes in the last 24h",
    href: "/events?action_category=Delete&signal=action_required&time_window=24h",
    fetchParams: new URLSearchParams({
      time_window: "24h",
      mode: "audit_trail",
      action_category: "Delete",
      signal_type: "action_required",
      limit: "50"
    })
  },
  {
    key: "creates",
    label: "Creates",
    emoji: "🟡",
    emptyMessage: "No creates needing review in the last 24h",
    href: "/events?action_category=Create&signal=attention&time_window=24h",
    fetchParams: new URLSearchParams({
      time_window: "24h",
      mode: "audit_trail",
      action_category: "Create",
      signal_type: "attention",
      limit: "50"
    })
  },
  {
    key: "api_keys",
    label: "API Keys",
    emoji: "🔑",
    emptyMessage: "No API key activity in the last 24h",
    href: "/events?action_category=API+Key&time_window=24h",
    fetchParams: new URLSearchParams({
      time_window: "24h",
      mode: "audit_trail",
      action_category: "API Key",
      limit: "50"
    })
  },
  {
    key: "denials",
    label: "Denials",
    emoji: "🚫",
    emptyMessage: "No denials in the last 24h",
    href: "/events?result=Denied&time_window=24h",
    fetchParams: new URLSearchParams({
      time_window: "24h",
      mode: "audit_trail",
      is_denied: "true",
      limit: "50"
    })
  },
  {
    key: "access",
    label: "Access changes",
    emoji: "🛡️",
    emptyMessage: "No access changes needing action in the last 24h",
    href: "/events?action_category=Security&signal=action_required&time_window=24h",
    fetchParams: new URLSearchParams({
      time_window: "24h",
      mode: "audit_trail",
      action_category: "Security",
      signal_type: "action_required",
      limit: "50"
    })
  }
];

function actorName(event: AuditEvent): string {
  const display = (event.actor_display_name || "").trim();
  const raw = (event.actor_raw_id || event.subject || event.actor || "").trim();
  if (display && display !== raw) return display;
  if (event.actor_email) return event.actor_email;
  return raw || event.actor || "unknown";
}

function groupKey(event: AuditEvent): string {
  return event.event_title || event.normalized_action || event.action || "(unspecified action)";
}

function formatAge(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "recently";
  const ageMin = Math.max(0, (Date.now() - ts) / 60000);
  if (ageMin < 1) return "just now";
  if (ageMin < 60) return `${Math.round(ageMin)}m ago`;
  const ageH = ageMin / 60;
  if (ageH < 24) return `${Math.round(ageH * 10) / 10}h ago`;
  return `${Math.round(ageH / 24)}d ago`;
}

function buildGroups(events: AuditEvent[], limit = 5): FeedGroup[] {
  const buckets = new Map<string, { count: number; latest: AuditEvent }>();
  for (const event of events) {
    const key = groupKey(event);
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, { count: 1, latest: event });
      continue;
    }
    existing.count += 1;
    if (Date.parse(event.timestamp) > Date.parse(existing.latest.timestamp)) {
      existing.latest = event;
    }
  }
  return [...buckets.entries()]
    .map(([action, info]) => ({
      action,
      count: info.count,
      lastActor: actorName(info.latest),
      lastAt: info.latest.timestamp
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit);
}

export default function ActionFeed() {
  const [state, setState] = useState<Record<string, FeedState>>(() => {
    const initial: Record<string, FeedState> = {};
    for (const cat of CATEGORIES) {
      initial[cat.key] = { status: "loading", groups: [], total: 0, error: null };
    }
    return initial;
  });

  useEffect(() => {
    const controller = new AbortController();
    for (const cat of CATEGORIES) {
      getEvents(cat.fetchParams, controller.signal)
        .then((response: EventListResponse) => {
          setState((prev) => ({
            ...prev,
            [cat.key]: {
              status: "loaded",
              groups: buildGroups(response.items),
              total: response.total,
              error: null
            }
          }));
        })
        .catch((err: Error) => {
          if (isAbortError(err)) return;
          setState((prev) => ({
            ...prev,
            [cat.key]: { status: "error", groups: [], total: 0, error: err.message }
          }));
        });
    }
    return () => controller.abort();
  }, []);

  const allLoaded = CATEGORIES.every((cat) => state[cat.key].status !== "loading");
  const allEmpty = allLoaded && CATEGORIES.every((cat) => state[cat.key].status === "loaded" && state[cat.key].total === 0);

  return (
    <section className="action-feed panel">
      <h2>Today&apos;s briefing</h2>
      <p className="muted">Grouped activity from the last 24 hours that may need your attention.</p>
      {allEmpty ? (
        <p className="action-feed-allclear">✅ Nothing unusual in the last 24h. Continue monitoring.</p>
      ) : null}
      <div className="action-feed-list">
        {CATEGORIES.map((cat) => {
          const entry = state[cat.key];
          if (entry.status === "loading") {
            return (
              <div key={cat.key} className="action-feed-row loading">
                <span className="action-feed-emoji">{cat.emoji}</span>
                <span className="muted">Loading {cat.label.toLowerCase()}…</span>
              </div>
            );
          }
          if (entry.status === "error") {
            return (
              <div key={cat.key} className="action-feed-row">
                <span className="action-feed-emoji">{cat.emoji}</span>
                <span className="panel-error">Could not load {cat.label.toLowerCase()} — {entry.error}</span>
              </div>
            );
          }
          if (entry.total === 0) {
            return (
              <div key={cat.key} className="action-feed-row empty">
                <span className="action-feed-emoji">✅</span>
                <span className="muted">{cat.emptyMessage}</span>
              </div>
            );
          }
          return (
            <div key={cat.key} className="action-feed-group">
              <div className="action-feed-group-header">
                <span className="action-feed-emoji">{cat.emoji}</span>
                <strong>{cat.label}</strong>
                <span className="muted">{entry.total.toLocaleString()} event{entry.total === 1 ? "" : "s"}</span>
                <Link className="action-feed-cta" href={cat.href}>View all →</Link>
              </div>
              <ul className="action-feed-items">
                {entry.groups.map((group) => (
                  <li key={`${cat.key}-${group.action}`}>
                    <Link href={cat.href}>
                      <strong>{group.action}</strong>{" "}
                      <span className="muted">({group.count.toLocaleString()} event{group.count === 1 ? "" : "s"})</span>
                      <span className="action-feed-meta"> — last by <strong>{group.lastActor}</strong>, {formatAge(group.lastAt)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
