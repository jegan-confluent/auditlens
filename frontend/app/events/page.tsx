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
import {
  getEvent,
  getEvents,
  getFilters,
  getSummary,
  getSystemStatus,
  isAbortError,
  updateEventTriage
} from "../../lib/api";
import {
  activeFilterLabels,
  allActivityFilters,
  defaultFilters,
  paramsFromFilters,
  summaryParamsFromFilters,
  type EventFilters
} from "../../lib/eventFilters";
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
    const controller = new AbortController();
    getFilters(controller.signal)
      .then(setOptions)
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getEvents(paramsFromFilters(filters, offset), controller.signal)
      .then(setData)
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message);
        getSystemStatus(controller.signal)
          .then(setSystem)
          .catch((sysErr) => {
            if (isAbortError(sysErr)) return;
            setSystem(null);
          });
      });
    return () => controller.abort();
  }, [filters, offset]);

  useEffect(() => {
    const controller = new AbortController();
    setSummaryLoading(true);
    setSummaryError(null);
    getSummary(summaryParamsFromFilters(filters), controller.signal)
      .then(setSummary)
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setSummaryError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setSummaryLoading(false);
      });
    return () => controller.abort();
  }, [filters]);

  const refreshSummary = () => {
    const controller = new AbortController();
    setSummaryLoading(true);
    setSummaryError(null);
    return getSummary(summaryParamsFromFilters(filters), controller.signal)
      .then(setSummary)
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setSummaryError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setSummaryLoading(false);
      });
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
  const isDecisionMode = filters.mode === "decision";

  if (error) return <main className="page"><ErrorState message={error} systemState={system?.db_writer_state || system?.consumer_state} /></main>;
  const renderedEvents = data ? data.items : [];

  return (
    <main className="page">
      <h1>Events</h1>
      {summary ? (
        <>
          <DecisionBanner summary={summary} onApplyDecision={applyDecisionFilters} />
          <NarrativeStrip summary={summary} />
          <SignalSummaryPanel summary={summary} onApplyFlow={applyFlowFilters} />
        </>
      ) : summaryLoading ? <LoadingState label="Loading decision summary" /> : summaryError ? <p className="active-filters">Decision summary unavailable: {summaryError}</p> : null}
      <FilterBar filters={filters} options={options} onChange={updateFilters} onReset={resetFilters} />
      <p className="active-filters">
        {isDecisionMode
          ? "Decision mode is active. Routine informational activity is hidden."
          : "Full audit trail mode is active. Routine read/list activity is included."}
      </p>
      {!data ? <LoadingState /> : renderedEvents.length ? <AuditEventTable events={renderedEvents} onSelect={selectEvent} /> : (
        <EmptyState
          diagnostics={
            isDecisionMode
              ? `No decision events matched this window. Total matching rows: ${data.total}. Switch to audit trail mode to inspect routine reads and informational activity.`
              : `Nothing matched these filters. Total matching rows: ${data.total}.`
          }
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
