"use client";

import { useEffect, useState } from "react";
import AuditEventTable from "../../components/AuditEventTable";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import LoadingState from "../../components/LoadingState";
import SummaryCards from "../../components/SummaryCards";
import SystemStatusPanel from "../../components/SystemStatusPanel";
import {
  getDeletions,
  getEvent,
  getEvents,
  getFailures,
  getReadinessStatus,
  getSummary,
  getSystemStatus,
  isAbortError
} from "../../lib/api";
import type { AuditEvent, EventListResponse, SummaryResponse, SystemStatus } from "../../lib/types";

type Panel<T> = { data: T | null; error: string | null };

function emptyPanel<T>(): Panel<T> {
  return { data: null, error: null };
}

function classifyLag(newestEvent: string | null): { tone: "fresh" | "warning" | "critical"; ageHours: number } | null {
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

export default function DashboardPage() {
  const [recent, setRecent] = useState<Panel<EventListResponse>>(emptyPanel());
  const [summary, setSummary] = useState<Panel<SummaryResponse>>(emptyPanel());
  const [failures, setFailures] = useState<Panel<EventListResponse>>(emptyPanel());
  const [deletions, setDeletions] = useState<Panel<EventListResponse>>(emptyPanel());
  const [system, setSystem] = useState<Panel<SystemStatus>>(emptyPanel());
  const [newestEvent, setNewestEvent] = useState<string | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [drawerError, setDrawerError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    const recentParams = new URLSearchParams({ limit: "10", time_window: "24h", mode: "decision" });
    const summaryParams = new URLSearchParams({ time_window: "24h", mode: "decision" });

    getEvents(recentParams, signal)
      .then((data) => setRecent({ data, error: null }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setRecent({ data: null, error: err.message });
      });
    getSummary(summaryParams, signal)
      .then((data) => setSummary({ data, error: null }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setSummary({ data: null, error: err.message });
      });
    getFailures(signal)
      .then((data) => setFailures({ data, error: null }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setFailures({ data: null, error: err.message });
      });
    getDeletions(signal)
      .then((data) => setDeletions({ data, error: null }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setDeletions({ data: null, error: err.message });
      });
    getSystemStatus(signal)
      .then((data) => setSystem({ data, error: null }))
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setSystem({ data: null, error: err.message });
      });
    getReadinessStatus(signal)
      .then((ready) => setNewestEvent(ready.newest_event ?? null))
      .catch((err) => {
        if (isAbortError(err)) return;
        setNewestEvent(null);
      });

    return () => controller.abort();
  }, []);

  const selectEvent = async (event: AuditEvent) => {
    try {
      setSelected(await getEvent(event.id));
      setDrawerError(null);
    } catch (err) {
      setDrawerError(err instanceof Error ? err.message : "Unable to load event detail");
    }
  };

  if (drawerError) {
    return <main className="page"><ErrorState message={drawerError} /></main>;
  }
  if (!recent.data && !recent.error) {
    return <main className="page"><LoadingState label="Loading recent decision events" /></main>;
  }

  const lag = classifyLag(newestEvent);

  return (
    <main className="page">
      {lag && lag.tone !== "fresh" ? (
        <div className={`lag-banner ${lag.tone}`} role="status">
          <strong>{lag.tone === "critical" ? "🚨" : "⚠️"} Data may be delayed</strong>
          <span> — last event received {formatAge(lag.ageHours)} ago.</span>
        </div>
      ) : null}

      {summary.data ? (
        <SummaryCards summary={summary.data} newestEvent={newestEvent} />
      ) : (
        <ErrorState message={summary.error || "Summary unavailable. Recent decision events are shown below."} />
      )}

      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Recent Decision Events</h2>
        {recent.error ? (
          <p className="panel-error">Could not load Recent Events — {recent.error}</p>
        ) : recent.data && recent.data.items.length ? (
          <AuditEventTable events={recent.data.items} onSelect={selectEvent} />
        ) : (
          <EmptyState />
        )}
      </section>

      <div className="grid" style={{ marginTop: 16 }}>
        <section className="panel">
          <h2>Failures</h2>
          {failures.error ? (
            <p className="panel-error">Could not load Failures — {failures.error}</p>
          ) : failures.data && failures.data.items.length ? (
            <AuditEventTable events={failures.data.items} onSelect={selectEvent} />
          ) : (
            <EmptyState diagnostics="No failed events in the current data set." />
          )}
        </section>
        <section className="panel">
          <h2>Deletions</h2>
          {deletions.error ? (
            <p className="panel-error">Could not load Deletions — {deletions.error}</p>
          ) : deletions.data && deletions.data.items.length ? (
            <AuditEventTable events={deletions.data.items} onSelect={selectEvent} />
          ) : (
            <EmptyState diagnostics="No delete-category events in the current data set." />
          )}
        </section>
      </div>

      {system.error ? (
        <p className="panel-error" style={{ marginTop: 16 }}>Could not load System status — {system.error}</p>
      ) : system.data ? (
        <div style={{ marginTop: 16 }}><SystemStatusPanel status={system.data} /></div>
      ) : null}

      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
