"use client";

import { useCallback, useEffect, useState } from "react";
import { getPatterns, markPatternExpected, suppressPattern } from "../lib/api";
import { formatResourceName } from "../lib/utils";
import type { EventPattern } from "../lib/types";

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function formatPatternActor(actor: string): string {
  if (actor.startsWith("{") || actor.startsWith("[")) return "Confluent (platform)";
  if (actor.startsWith("User:")) return truncate(actor.slice(5), 40);
  if (actor.startsWith("ServiceAccount:")) return truncate(actor.slice(15), 40);
  return truncate(actor, 40);
}

function isServiceAccount(actor_type: string | null | undefined): boolean {
  return actor_type === "service_account";
}

export default function RecurringPatterns() {
  const [patterns, setPatterns] = useState<EventPattern[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [acting, setActing] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getPatterns("active")
      .then((res) => {
        setPatterns(res.patterns);
        setTotal(res.total);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSuppress(id: number) {
    setActing(id);
    setActionError(null);
    try {
      await suppressPattern(id, 24);
      load();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(`Suppress failed: ${msg}`);
    } finally {
      setActing(null);
    }
  }

  async function handleMarkExpected(id: number) {
    setActing(id);
    setActionError(null);
    try {
      await markPatternExpected(id);
      load();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setActionError(`Mark expected failed: ${msg}`);
    } finally {
      setActing(null);
    }
  }

  if (!loading && !error && total === 0) return null;

  return (
    <div className="recurring-patterns-section">
      <button
        className="recurring-patterns-header"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
      >
        <span className="recurring-patterns-chevron">{collapsed ? "▶" : "▼"}</span>
        <span>Recurring Patterns</span>
        {total > 0 && (
          <span className="recurring-patterns-badge">{total}</span>
        )}
        <span className="recurring-patterns-hint muted">
          — (actor, action, resource) combos firing &gt;10× in 10 min
        </span>
      </button>

      {!collapsed && (
        <div className="recurring-patterns-body">
          {loading && <p className="muted">Loading patterns…</p>}
          {error && <p className="error-text">Failed to load patterns: {error}</p>}
          {actionError && <p className="error-text">{actionError}</p>}

          {patterns.length > 0 && (
            <table className="recurring-patterns-table">
              <thead>
                <tr>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>Count</th>
                  <th>Last Seen</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {patterns.map((p) => (
                  <tr key={p.id}>
                    <td title={p.actor}>
                      {p.actor_display_name ? truncate(p.actor_display_name, 40) : formatPatternActor(p.actor)}
                      {isServiceAccount(p.actor_type) && <span className="actor-badge">SA</span>}
                    </td>
                    <td title={p.action}>{truncate(p.action, 50)}</td>
                    <td title={p.resource_name ?? ""}>{p.resource_name ? truncate(formatResourceName(p.resource_name), 40) : <span className="muted">—</span>}</td>
                    <td className="pattern-count">{p.occurrence_count.toLocaleString()}×</td>
                    <td className="muted">{relativeTime(p.last_seen_at)}</td>
                    <td className="pattern-action-buttons">
                      <button
                        className="btn-suppress"
                        disabled={acting === p.id}
                        onClick={() => handleSuppress(p.id)}
                        title="Suppress for 24 hours — hides from decision mode"
                      >
                        Suppress 24h
                      </button>
                      <button
                        className="btn-expected"
                        disabled={acting === p.id}
                        onClick={() => handleMarkExpected(p.id)}
                        title="Mark as expected automation — permanently hides from decision mode"
                      >
                        Mark Expected
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
