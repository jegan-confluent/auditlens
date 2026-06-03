"use client";

import { useEffect, useState } from "react";
import { compareEvents, type CompareResponse, type PeriodStats } from "../lib/api";
import { encodeTimeWindow } from "../lib/eventFilters";

// Same preset shape as the FilterBar time-window select so the comparison
// uses the periods the user is already used to. No new date-picker library.
const PRESETS: Array<{ value: string; label: string }> = [
  { value: "30m", label: "Last 30 min" },
  { value: "2h", label: "Last 2h" },
  { value: "4h", label: "Last 4h" },
  { value: "12h", label: "Last 12h" },
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7d" },
  { value: "30d", label: "Last 30d" },
];

function formatTopActor(stats: PeriodStats): string {
  const first = stats.top_actors[0];
  return first ? `${first.name} (${first.count})` : "—";
}

function formatTopMethod(stats: PeriodStats): string {
  const first = stats.top_methods[0];
  return first ? `${first.action} (${first.count})` : "—";
}

function actionRequiredCount(stats: PeriodStats): number {
  return stats.by_signal_type["action_required"] || 0;
}

function PeriodCard({ label, stats }: { label: string; stats: PeriodStats }) {
  return (
    <div
      className="filter-panel"
      style={{ flex: 1, minWidth: 0, padding: "10px 12px" }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: "0.85em", color: "var(--muted)", marginBottom: 8 }}>
        Window: {stats.window}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", rowGap: 4, columnGap: 12 }}>
        <span className="muted">Total</span>
        <span><strong>{stats.total.toLocaleString()}</strong></span>
        <span className="muted">Action required</span>
        <span><strong>{actionRequiredCount(stats).toLocaleString()}</strong></span>
        <span className="muted">Top actor</span>
        <span>{formatTopActor(stats)}</span>
        <span className="muted">Top method</span>
        <span>{formatTopMethod(stats)}</span>
      </div>
    </div>
  );
}

export default function ComparePeriodsPanel() {
  const [open, setOpen] = useState(false);
  const [periodA, setPeriodA] = useState("24h");
  const [periodB, setPeriodB] = useState("7d");
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const a = encodeTimeWindow(periodA);
    const b = encodeTimeWindow(periodB);
    if (!a || !b) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    compareEvents(a, b, controller.signal)
      .then(setData)
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, periodA, periodB]);

  if (!open) {
    return (
      <div style={{ marginBottom: 12 }}>
        <button
          type="button"
          className="quick-filter"
          onClick={() => setOpen(true)}
          aria-expanded={false}
        >
          Compare periods
        </button>
      </div>
    );
  }

  return (
    <section className="filter-panel" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <strong>Compare periods</strong>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          Period A
          <select value={periodA} onChange={(e) => setPeriodA(e.target.value)} aria-label="Period A">
            {PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          Period B
          <select value={periodB} onChange={(e) => setPeriodB(e.target.value)} aria-label="Period B">
            {PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>
        <button type="button" className="quick-filter" onClick={() => setOpen(false)}>
          Hide
        </button>
      </div>
      {loading ? (
        <p className="muted" style={{ margin: 0 }}>Loading comparison…</p>
      ) : error ? (
        <p className="error-text" style={{ margin: 0 }}>Compare failed: {error}</p>
      ) : data ? (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <PeriodCard label="Period A" stats={data.period_a} />
          <PeriodCard label="Period B" stats={data.period_b} />
        </div>
      ) : null}
    </section>
  );
}
