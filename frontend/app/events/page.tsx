"use client";

import { useEffect, useState } from "react";
import AuditEventTable from "../../components/AuditEventTable";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import FilterBar, { defaultFilters, type EventFilters } from "../../components/FilterBar";
import LoadingState from "../../components/LoadingState";
import { getEvent, getEvents, getFilters } from "../../lib/api";
import type { AuditEvent, EventListResponse, FilterOptions } from "../../lib/types";

function paramsFromFilters(filters: EventFilters, offset: number) {
  const params = new URLSearchParams({ limit: "100", offset: String(offset) });
  Object.entries(filters).forEach(([key, value]) => {
    if (value.trim()) params.set(key, value.trim());
  });
  return params;
}

export default function EventsPage() {
  const [filters, setFilters] = useState<EventFilters>(defaultFilters);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [data, setData] = useState<EventListResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getFilters().then(setOptions).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    setError(null);
    getEvents(paramsFromFilters(filters, offset)).then(setData).catch((err: Error) => setError(err.message));
  }, [filters, offset]);

  const selectEvent = async (event: AuditEvent) => setSelected(await getEvent(event.id));
  const updateFilters = (next: EventFilters) => {
    setOffset(0);
    setFilters(next);
  };

  if (error) return <main className="page"><ErrorState message={error} /></main>;

  return (
    <main className="page">
      <h1>Events</h1>
      <FilterBar filters={filters} options={options} onChange={updateFilters} onReset={() => updateFilters(defaultFilters)} />
      {!data ? <LoadingState /> : data.items.length ? <AuditEventTable events={data.items} onSelect={selectEvent} /> : <EmptyState diagnostics={`Rows returned: 0. Total matching rows: ${data.total}.`} />}
      {data ? (
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - data.limit))}>Previous</button>
          <span className="muted">Showing {offset + 1}-{Math.min(offset + data.items.length, data.total)} of {data.total}</span>
          <button disabled={offset + data.limit >= data.total} onClick={() => setOffset(offset + data.limit)}>Next</button>
        </div>
      ) : null}
      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
