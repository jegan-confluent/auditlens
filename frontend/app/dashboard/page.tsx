"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import ActionFeed from "../../components/ActionFeed";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import NarrativeStrip from "../../components/NarrativeStrip";
import SignalSummaryPanel from "../../components/SignalSummaryPanel";
import SystemStatusPanel from "../../components/SystemStatusPanel";
import TopActors from "../../components/TopActors";
import { getReadinessStatus, getSummary, getSystemStatus, isAbortError } from "../../lib/api";
import { encodeTimeWindow, type EventFilters } from "../../lib/eventFilters";
import type { SummaryResponse, SystemStatus } from "../../lib/types";

type TimeWindow = "1h" | "6h" | "24h" | "7d";
const TIME_WINDOW_OPTIONS = ["1h", "6h", "24h", "7d"] as const;

type Lag = { tone: "fresh" | "warning" | "critical"; ageHours: number };

function classifyLag(newestEvent: string | null): Lag | null {
  if (!newestEvent) return null;
  const ts = Date.parse(newestEvent);
  if (Number.isNaN(ts)) return null;
  const ageHours = (Date.now() - ts) / (60 * 60 * 1000);
  if (ageHours >= 6) return { tone: "critical", ageHours };
  if (ageHours >= 1) return { tone: "warning", ageHours };
  return { tone: "fresh", ageHours };
}

function formatAge(ageHours: number): string {
  if (ageHours < 1) {
    const mins = Math.max(1, Math.round(ageHours * 60));
    return `${mins} min`;
  }
  const rounded = Math.round(ageHours * 10) / 10;
  return `${rounded} h`;
}

type Panel<T> = { data: T | null; error: string | null; loading: boolean };

function emptyPanel<T>(): Panel<T> {
  return { data: null, error: null, loading: true };
}

function TimeWindowPills({
  value,
  onChange,
}: {
  value: TimeWindow;
  onChange: (v: TimeWindow) => void;
}) {
  return (
    <div className="time-window-pills">
      {TIME_WINDOW_OPTIONS.map((opt) => (
        <button
          key={opt}
          type="button"
          className={`time-window-pill${value === opt ? " active" : ""}`}
          onClick={() => onChange(opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

const HEATMAP_COLORS = ["#F1EFE8", "#FAC775", "#EF9F27", "#E24B4A"] as const;

function heatColor(count: number): string {
  if (count === 0) return HEATMAP_COLORS[0];
  if (count <= 10) return HEATMAP_COLORS[1];
  if (count <= 50) return HEATMAP_COLORS[2];
  return HEATMAP_COLORS[3];
}

function EnvironmentBreakdown({ byEnvironment }: { byEnvironment: Record<string, number> }) {
  const entries = Object.entries(byEnvironment).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = entries[0]?.[1] ?? 1;
  return (
    <div className="insight-breakdown" style={{ marginBottom: 8 }}>
      <span className="muted" style={{ fontSize: 12 }}>By environment</span>
      {entries.map(([env, count]) => (
        <div key={env} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <span className="muted" style={{ fontSize: 11, width: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{env}</span>
          <div style={{ flex: 1, background: "#F1EFE8", borderRadius: 2, height: 8 }}>
            <div style={{ width: `${Math.round((count / max) * 100)}%`, background: "#EF9F27", height: 8, borderRadius: 2 }} />
          </div>
          <span className="muted" style={{ fontSize: 11, width: 50, textAlign: "right" }}>{count.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function HourlyHeatmap({ byHour }: { byHour: number[] }) {
  const hours = byHour.length === 24 ? byHour : Array(24).fill(0).map((_, i) => byHour[i] ?? 0);
  return (
    <div className="insight-breakdown" style={{ marginBottom: 8 }}>
      <span className="muted" style={{ fontSize: 12 }}>Activity by hour (UTC, last 7d)</span>
      <div style={{ display: "flex", gap: 2, marginTop: 4 }}>
        {hours.map((count, hr) => (
          <div
            key={hr}
            title={`${String(hr).padStart(2, "0")}:00 UTC — ${count.toLocaleString()} events`}
            style={{ flex: 1, height: 20, background: heatColor(count), borderRadius: 2, cursor: "default" }}
          />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        {["0", "6", "12", "18", "24"].map((label) => (
          <span key={label} className="muted" style={{ fontSize: 10 }}>{label}</span>
        ))}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();

  const navigateToEvents = (patch: Partial<EventFilters>) => {
    const params = new URLSearchParams();
    (Object.entries(patch) as Array<[string, string | undefined]>).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    router.push(`/events?${params.toString()}`);
  };

  const [timeWindow, setTimeWindow] = useState<TimeWindow>(() => {
    if (typeof window === "undefined") return "24h";
    const saved = localStorage.getItem("dashboard_time_window");
    if (saved === "1h" || saved === "6h" || saved === "24h" || saved === "7d") return saved;
    return "24h";
  });
  const [system, setSystem] = useState<Panel<SystemStatus>>(emptyPanel());
  const [newestEvent, setNewestEvent] = useState<string | null>(null);
  const [readyError, setReadyError] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);

  const onTimeWindowChange = (val: TimeWindow) => {
    setSummary(null);
    setTimeWindow(val);
    localStorage.setItem("dashboard_time_window", val);
  };

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    getSystemStatus(signal)
      .then((data) => setSystem({ data, error: null, loading: false }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setSystem({ data: null, error: err.message, loading: false });
      });

    getReadinessStatus(signal)
      .then((ready) => {
        setNewestEvent(ready.newest_event ?? null);
        if (!ready.ok) setReadyError(`/ready returned status ${ready.status}`);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setNewestEvent(null);
        setReadyError(err instanceof Error ? err.message : "Failed to check forwarder readiness");
      });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getSummary(new URLSearchParams({ time_window: encodeTimeWindow(timeWindow), mode: "decision" }), controller.signal)
      .then(setSummary)
      .catch((err) => {
        if (isAbortError(err)) return;
      });
    return () => controller.abort();
  }, [timeWindow]);

  const lag = classifyLag(newestEvent);

  return (
    <main className="page">
      {summary ? <NarrativeStrip summary={summary} timeWindow={timeWindow} /> : null}
      {lag && lag.tone === "critical" ? (
        <div className="lag-banner critical" role="status">
          <strong>🚨 Forwarder significantly behind</strong>
          <span> — last event received {formatAge(lag.ageHours)} ago.</span>
        </div>
      ) : lag && lag.tone === "warning" ? (
        <div className="lag-banner warning" role="status">
          <strong>⚠️ Data may be delayed</strong>
          <span> — last event received {formatAge(lag.ageHours)} ago.</span>
        </div>
      ) : null}

      {readyError ? (
        // The /ready endpoint this probes is the API container's (it
        // verifies DB connectivity + last event freshness). Old wording
        // said "Forwarder readiness check failed" which sent operators
        // chasing the wrong process when the DB was the actual cause.
        <p className="panel-error">API readiness check failed — {readyError}</p>
      ) : null}

      {summary ? (
        <SignalSummaryPanel
          summary={summary}
          onApplyFlow={navigateToEvents}
          onTierSelect={(tier) => {
            if (!tier) return;
            const patch = tier === "noise"
              ? { mode: "audit_trail" as const, signal: "noise", hide_noise: "false" }
              : { mode: "decision" as const, signal: tier, hide_noise: "true" };
            navigateToEvents(patch);
          }}
        />
      ) : null}
      {summary?.by_environment && Object.keys(summary.by_environment).length > 1 ? (
        <EnvironmentBreakdown byEnvironment={summary.by_environment} />
      ) : null}
      {summary?.by_hour && summary.by_hour.some((n) => n > 0) ? (
        <HourlyHeatmap byHour={summary.by_hour} />
      ) : null}
      <ActionFeed
        timeWindow={timeWindow}
        timeWindowSelector={
          <TimeWindowPills value={timeWindow} onChange={onTimeWindowChange} />
        }
      />
      <TopActors timeWindow={timeWindow} summary={summary} />

      {system.loading ? (
        <LoadingState label="Loading system health" />
      ) : system.error ? (
        <ErrorState message={`Could not load System status — ${system.error}`} />
      ) : system.data ? (
        <div style={{ marginTop: 16 }}><SystemStatusPanel status={system.data} /></div>
      ) : null}
    </main>
  );
}
