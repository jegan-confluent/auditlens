"use client";

import { useEffect, useState } from "react";
import AuditEventTable from "../../components/AuditEventTable";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import LoadingState from "../../components/LoadingState";
import SummaryCards from "../../components/SummaryCards";
import SystemStatusPanel from "../../components/SystemStatusPanel";
import { getDeletions, getEvent, getEvents, getFailures, getSummary, getSystemStatus } from "../../lib/api";
import type { AuditEvent, EventListResponse, SummaryResponse, SystemStatus } from "../../lib/types";

export default function DashboardPage() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [recent, setRecent] = useState<EventListResponse | null>(null);
  const [failures, setFailures] = useState<EventListResponse | null>(null);
  const [deletions, setDeletions] = useState<EventListResponse | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const emptyEvents: EventListResponse = { items: [], limit: 5, offset: 0, total: 0, scanned_events: 0, signal_filter_applied: false, hide_noise_applied: false, result_limit_reached: false };

  useEffect(() => {
    getEvents(new URLSearchParams({ limit: "10", time_window: "2h", mode: "decision" })).then(setRecent).catch((err: Error) => setError(err.message));
    getSummary(new URLSearchParams({ time_window: "2h", mode: "decision" })).then((data) => {
      setSummary(data);
      setLastUpdated(new Date().toLocaleTimeString());
    }).catch((err: Error) => setError(err.message));
    getFailures().then(setFailures).catch(() => setFailures(emptyEvents));
    getDeletions().then(setDeletions).catch(() => setDeletions(emptyEvents));
    getSystemStatus().then(setSystem).catch(() => setSystem(null));
  }, []);

  const selectEvent = async (event: AuditEvent) => {
    try {
      setSelected(await getEvent(event.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load event detail");
    }
  };

  if (error) return <main className="page"><ErrorState message={error} /></main>;
  if (!recent) return <main className="page"><LoadingState label="Loading recent decision events" /></main>;
  const failureEvents = failures || emptyEvents;
  const deletionEvents = deletions || emptyEvents;

  return (
    <main className="page">
      {summary ? <SummaryCards summary={summary} lastUpdated={lastUpdated} /> : <ErrorState message="Summary is still loading or unavailable. Recent decision events are shown below." />}
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Recent Decision Events</h2>
        {recent.items.length ? <AuditEventTable events={recent.items} onSelect={selectEvent} /> : <EmptyState />}
      </section>
      <div className="grid" style={{ marginTop: 16 }}>
        <section className="panel">
          <h2>Failures</h2>
          {failureEvents.items.length ? <AuditEventTable events={failureEvents.items} onSelect={selectEvent} /> : <EmptyState diagnostics="No failed events in the current data set." />}
        </section>
        <section className="panel">
          <h2>Deletions</h2>
          {deletionEvents.items.length ? <AuditEventTable events={deletionEvents.items} onSelect={selectEvent} /> : <EmptyState diagnostics="No delete-category events in the current data set." />}
        </section>
      </div>
      {system ? <div style={{ marginTop: 16 }}><SystemStatusPanel status={system} /></div> : null}
      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
