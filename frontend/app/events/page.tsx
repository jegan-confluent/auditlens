"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import AuditEventTable from "../../components/AuditEventTable";
import DecisionBanner from "../../components/DecisionBanner";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
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
  isAbortError
} from "../../lib/api";
import {
  activeFilterLabels,
  allActivityFilters,
  defaultFilters,
  humanTimeWindowLabel,
  paramsFromFilters,
  summaryParamsFromFilters,
  type EventFilters
} from "../../lib/eventFilters";
import type { AuditEvent, EventListResponse, FilterOptions, SummaryResponse, SystemStatus } from "../../lib/types";

// String-typed filter keys (everything except `mode`, which is a literal
// union we narrow separately below).
const URL_STRING_KEYS = [
  "time_window",
  "resource_type",
  "resource",
  "cluster_name",
  "environment_name",
  "action_category",
  "actor",
  "result",
  "signal",
  "hide_noise",
  "impact_type"
] as const satisfies ReadonlyArray<Exclude<keyof EventFilters, "mode">>;

function filtersFromSearchParams(params: URLSearchParams, base: EventFilters): EventFilters {
  const next: EventFilters = { ...base };
  let touched = false;
  for (const key of URL_STRING_KEYS) {
    const value = params.get(key);
    if (value !== null) {
      next[key] = value;
      touched = true;
    }
  }
  const modeParam = params.get("mode");
  if (modeParam === "decision" || modeParam === "audit_trail") {
    next.mode = modeParam;
    touched = true;
  }
  // Accept legacy/backend-style ?signal_type= as a synonym for ?signal= so
  // dashboard links that route via the backend param name still seed the
  // filter state correctly.
  const signalType = params.get("signal_type");
  if (signalType !== null && !params.has("signal")) {
    next.signal = signalType;
    touched = true;
  }
  return touched ? next : base;
}

export default function EventsPage() {
  return (
    <Suspense fallback={<main className="page"><LoadingState label="Loading events" /></main>}>
      <EventsPageInner />
    </Suspense>
  );
}

function EventsPageInner() {
  const searchParams = useSearchParams();
  const initialFilters = useMemo(
    () => filtersFromSearchParams(new URLSearchParams(searchParams.toString()), defaultFilters),
    // Seed once from the URL on first mount; later filter mutations stay in
    // component state. Re-reading on every searchParams change would fight
    // the user's interactions with FilterBar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );
  const [filters, setFilters] = useState<EventFilters>(initialFilters);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [data, setData] = useState<EventListResponse | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<AuditEvent | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

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

  const onToggleExpand = (event: AuditEvent) => {
    if (expandedId === event.id) {
      setExpandedId(null);
      setExpandedDetail(null);
      setExpandedError(null);
      return;
    }
    setExpandedId(event.id);
    setExpandedDetail(null);
    setExpandedError(null);
    setExpandedLoading(true);
    getEvent(event.id)
      .then((full) => {
        setExpandedDetail(full);
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setExpandedError(err.message);
      })
      .finally(() => setExpandedLoading(false));
  };

  const updateFilters = (next: EventFilters) => {
    setOffset(0);
    setFilters(next);
    setExpandedId(null);
    setExpandedDetail(null);
  };
  const resetFilters = () => updateFilters(defaultFilters);
  const showAllActivity = () => updateFilters(allActivityFilters);
  const applyFlowFilters = (patch: Partial<EventFilters>) => updateFilters({ ...filters, ...patch });
  const applyDecisionFilters = (patch: Partial<EventFilters>) => updateFilters({ ...filters, ...patch });
  const activeFilters = activeFilterLabels(filters);
  const isDecisionMode = filters.mode === "decision";
  const timeWindowLabel = humanTimeWindowLabel(filters.time_window);

  if (error) return <main className="page"><ErrorState message={error} systemState={system?.db_writer_state || system?.consumer_state} /></main>;
  const renderedEvents = data ? data.items : [];

  return (
    <main className="page">
      <h1>Events</h1>
      {summary ? (
        <>
          <DecisionBanner summary={summary} timeWindowLabel={timeWindowLabel} onApplyDecision={applyDecisionFilters} />
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
      {!data ? <LoadingState /> : renderedEvents.length ? (
        <AuditEventTable
          events={renderedEvents}
          expandedId={expandedId}
          expandedDetail={expandedDetail}
          expandedLoading={expandedLoading}
          expandedError={expandedError}
          onToggleExpand={onToggleExpand}
        />
      ) : (
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
    </main>
  );
}
