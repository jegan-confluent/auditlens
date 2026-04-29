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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getSummary(),
      getEvents(new URLSearchParams({ limit: "10" })),
      getFailures(),
      getDeletions(),
      getSystemStatus()
    ])
      .then(([summaryData, recentData, failuresData, deletionsData, systemData]) => {
        setSummary(summaryData);
        setRecent(recentData);
        setFailures(failuresData);
        setDeletions(deletionsData);
        setSystem(systemData);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const selectEvent = async (event: AuditEvent) => setSelected(await getEvent(event.id));

  if (error) return <main className="page"><ErrorState message={error} /></main>;
  if (!summary || !recent || !failures || !deletions || !system) return <main className="page"><LoadingState /></main>;

  return (
    <main className="page">
      <SummaryCards summary={summary} />
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Recent Events</h2>
        {recent.items.length ? <AuditEventTable events={recent.items} onSelect={selectEvent} /> : <EmptyState />}
      </section>
      <div className="grid" style={{ marginTop: 16 }}>
        <section className="panel">
          <h2>Failures</h2>
          {failures.items.length ? <AuditEventTable events={failures.items} onSelect={selectEvent} /> : <EmptyState diagnostics="No failed events in the current data set." />}
        </section>
        <section className="panel">
          <h2>Deletions</h2>
          {deletions.items.length ? <AuditEventTable events={deletions.items} onSelect={selectEvent} /> : <EmptyState diagnostics="No delete-category events in the current data set." />}
        </section>
      </div>
      <div style={{ marginTop: 16 }}><SystemStatusPanel status={system} /></div>
      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
