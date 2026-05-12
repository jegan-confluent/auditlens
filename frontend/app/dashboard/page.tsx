"use client";

import { useEffect, useState } from "react";
import ActionFeed from "../../components/ActionFeed";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import SystemStatusPanel from "../../components/SystemStatusPanel";
import TopActors from "../../components/TopActors";
import { getReadinessStatus, getSystemStatus, isAbortError } from "../../lib/api";
import type { SystemStatus } from "../../lib/types";

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

export default function DashboardPage() {
  const [system, setSystem] = useState<Panel<SystemStatus>>(emptyPanel());
  const [newestEvent, setNewestEvent] = useState<string | null>(null);
  const [readyError, setReadyError] = useState<string | null>(null);

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

  const lag = classifyLag(newestEvent);

  return (
    <main className="page">
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
        <p className="panel-error">Forwarder readiness check failed — {readyError}</p>
      ) : null}

      <ActionFeed timeWindow="24h" />
      <TopActors timeWindow="24h" />

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
