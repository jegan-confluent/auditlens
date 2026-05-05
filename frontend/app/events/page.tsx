"use client";

import { useEffect, useState } from "react";
import AuditEventTable from "../../components/AuditEventTable";
import DecisionBanner from "../../components/DecisionBanner";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import FilterBar from "../../components/FilterBar";
import LoadingState from "../../components/LoadingState";
import NarrativeStrip from "../../components/NarrativeStrip";
import SignalSummaryPanel from "../../components/SignalSummaryPanel";
import { getEvent, getEvents, getFilters, getSummary, getSystemStatus, updateEventTriage } from "../../lib/api";
import { activeFilterLabels, allActivityFilters, defaultFilters, paramsFromFilters, summaryParamsFromFilters, type EventFilters } from "../../lib/eventFilters";
import type { AuditEvent, EventListResponse, FilterOptions, SummaryResponse, SystemStatus } from "../../lib/types";

export default function EventsPage() {
  const [filters, setFilters] = useState<EventFilters>(defaultFilters);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [data, setData] = useState<EventListResponse | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);

  useEffect(() => {
    getFilters().then(setOptions).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    setError(null);
    getEvents(paramsFromFilters(filters, offset))
      .then(setData)
      .catch((err: Error) => {
        setError(err.message);
        getSystemStatus().then(setSystem).catch(() => setSystem(null));
      });
  }, [filters, offset]);

  useEffect(() => {
    setSummaryLoading(true);
    setSummaryError(null);
    getSummary(summaryParamsFromFilters(filters))
      .then(setSummary)
      .catch((err: Error) => setSummaryError(err.message))
      .finally(() => setSummaryLoading(false));
  }, [filters]);

  const refreshSummary = () => {
    setSummaryLoading(true);
    setSummaryError(null);
    return getSummary(summaryParamsFromFilters(filters))
      .then(setSummary)
      .catch((err: Error) => setSummaryError(err.message))
      .finally(() => setSummaryLoading(false));
  };

  const selectEvent = async (event: AuditEvent) => {
    try {
      setSelected(await getEvent(event.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load event detail");
    }
  };
  const handleTriage = async (status: string) => {
    if (!selected) return;
    try {
      const updated = await updateEventTriage(selected.id, status);
      setSelected(updated);
      setData((current) => current ? { ...current, items: current.items.map((item) => item.id === updated.id ? { ...item, ...updated } : item) } : current);
      await refreshSummary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update triage status");
    }
  };
  const updateFilters = (next: EventFilters) => {
    setOffset(0);
    setFilters(next);
  };
  const resetFilters = () => updateFilters(defaultFilters);
  const showAllActivity = () => updateFilters(allActivityFilters);
  const applyFlowFilters = (patch: Partial<EventFilters>) => updateFilters({ ...filters, ...patch });
  const applyDecisionFilters = (patch: Partial<EventFilters>) => updateFilters({ ...filters, ...patch });
  const activeFilters = activeFilterLabels(filters);

  if (error) return <main className="page"><ErrorState message={error} systemState={system?.db_writer_state || system?.consumer_state} /></main>;
  const renderedEvents = data ? data.items : [];

  return (
    <main className="page">
      <h1>Events</h1>
      <div className="mode-bar">
        <strong>Latest mode: showing important activity from the last 2 hours. Routine noise is hidden. Only attention and action-required events are shown.</strong>
        <button onClick={resetFilters}>Latest changes</button>
        <button onClick={showAllActivity}>Show all activity</button>
        <button onClick={() => updateFilters({ ...filters, impact_type: "destructive", hide_noise: "false", signal: "" })}>Show only destructive changes</button>
      </div>
      {summary ? (
        <>
          <DecisionBanner summary={summary} onApplyDecision={applyDecisionFilters} />
          <NarrativeStrip summary={summary} />
          <SignalSummaryPanel summary={summary} onApplyFlow={applyFlowFilters} />
        </>
      ) : summaryLoading ? <LoadingState label="Loading decision summary" /> : summaryError ? <p className="active-filters">Decision summary unavailable: {summaryError}</p> : null}
      <FilterBar filters={filters} options={options} onChange={updateFilters} onReset={resetFilters} />
      {(filters.hide_noise === "true" || filters.signal) ? <p className="active-filters">Some events are hidden due to filters. Use Show all activity to remove signal and noise filters.</p> : null}
      {filters.hide_noise === "true" ? <p className="active-filters">Routine noise hidden. Use Show Noise to include authentication and authorization checks.</p> : null}
      {!data ? <LoadingState /> : renderedEvents.length ? <AuditEventTable events={renderedEvents} onSelect={selectEvent} /> : (
        <EmptyState
          diagnostics={filters.hide_noise === "true" ? "Only routine noise matched this window. Show noise to inspect authentication and authorization checks." : `Nothing matched these filters. Total matching rows: ${data.total}.`}
          activeFilters={activeFilters}
          onReset={resetFilters}
          onShowAll={showAllActivity}
        />
      )}
      {data ? (
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - data.limit))}>Previous</button>
          <span className="muted">Showing {offset + 1}-{Math.min(offset + data.items.length, data.total)} of {data.total}</span>
          <button disabled={offset + data.limit >= data.total} onClick={() => setOffset(offset + data.limit)}>Next</button>
        </div>
      ) : null}
      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} onTriage={handleTriage} />
    </main>
  );
}
