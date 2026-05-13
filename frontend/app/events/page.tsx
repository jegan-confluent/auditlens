"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ActorActivityPanel from "../../components/ActorActivityPanel";
import AuditEventTable from "../../components/AuditEventTable";
import EmptyState from "../../components/EmptyState";
import ErrorState from "../../components/ErrorState";
import FilterBar from "../../components/FilterBar";
import LoadingState from "../../components/LoadingState";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import RecurringPatterns from "../../components/RecurringPatterns";
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

// Phase 2 Fix 4: relative-time formatter for the "Last event: …" line.
// Distinct from the System-page formatRelative — this one rounds to whole
// minutes / hours so the Events header doesn't flicker every second.
function formatRelativeMinutes(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// Zone 1: Status strip — always-visible one-line sticky header
function StatusStrip({
  system,
  summary,
  filters,
  onFilterChange,
}: {
  system: SystemStatus | null;
  summary: SummaryResponse | null;
  filters: EventFilters;
  onFilterChange: (patch: Partial<EventFilters>) => void;
}) {
  const lag = system?.pipeline_lag ?? null;
  const dbLatest = lag?.db_latest_event_at ?? null;
  const status = lag?.status ?? "unknown";
  const lastEventText = dbLatest ? formatRelativeMinutes(dbLatest) : "unknown";
  const attentionCount = summary?.action_required_count ?? 0;

  let statusDot: string;
  let statusText: string;
  if (status === "healthy") { statusDot = "🟢"; statusText = "Connected"; }
  else if (status === "degraded") { statusDot = "🟡"; statusText = "Degraded"; }
  else if (status === "stalled") { statusDot = "🔴"; statusText = "Stalled"; }
  else { statusDot = "⚪"; statusText = "Unknown"; }

  const TIME_WINDOW_OPTIONS = ["30m", "2h", "4h", "12h", "24h", "7d", "30d"];

  return (
    <div className="events-status-strip">
      <span className="events-status-brand">AuditLens</span>
      <span className="events-status-sep">·</span>
      <span>Last event: {lastEventText}</span>
      {attentionCount > 0 ? (
        <>
          <span className="events-status-sep">·</span>
          <button
            className="events-status-attention"
            onClick={() => onFilterChange({ signal: "action_required" })}
          >
            {attentionCount} need attention
          </button>
        </>
      ) : null}
      <span className="events-status-sep">·</span>
      <span>{statusDot} {statusText}</span>
      <span className="events-status-sep">·</span>
      <select
        className="events-status-time-window"
        value={filters.time_window}
        onChange={(e) => onFilterChange({ time_window: e.target.value })}
        aria-label="Time window"
      >
        {TIME_WINDOW_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>{opt} ▼</option>
        ))}
      </select>
    </div>
  );
}

// Zone 2: Incident card
function formatSubject(subject: string): string {
  if (subject.startsWith("{") || subject.startsWith("[")) return "Confluent (platform)";
  if (subject.length > 30 && !subject.includes(" ") && !subject.includes("@")) {
    return subject.slice(0, 20) + "...";
  }
  return subject;
}

function IncidentCard({
  summary,
  timeWindowLabel,
  filters,
  onCategoryFilter,
  onInvestigateActor,
  onSeeAll,
}: {
  summary: SummaryResponse | null;
  timeWindowLabel: string;
  filters: EventFilters;
  onCategoryFilter: (patch: Partial<EventFilters>) => void;
  onInvestigateActor: (actor: string) => void;
  onSeeAll: () => void;
}): React.ReactElement | null {
  if (!summary) return null;

  const categoryCards = (
    <div className="incident-category-cards">
      {[
        { key: "destructive", label: "Destructive actions", count: summary.destructive_count, isActive: filters.impact_type === "destructive" },
        { key: "configuration_change", label: "Configuration changes", count: summary.configuration_change_count, isActive: filters.impact_type === "configuration_change" },
        { key: "access_change", label: "Access changes", count: summary.access_change_count, isActive: filters.impact_type === "access_change" },
        { key: "failures", label: "Failures / denied", count: summary.failure_count + summary.denied_count, isActive: filters.result === "Failure" },
      ].map(({ key, label, count, isActive }) => {
        const activePatch: Partial<EventFilters> = key === "failures"
          ? { result: "Failure", impact_type: "", mode: "audit_trail", signal: "", hide_noise: "false" }
          : { impact_type: key, mode: "audit_trail", signal: "", hide_noise: "false" };
        const clearPatch: Partial<EventFilters> = key === "failures" ? { result: "" } : { impact_type: "" };
        return (
          <button
            key={key}
            type="button"
            className={`incident-category-card${isActive ? " active" : ""}`}
            onClick={() => onCategoryFilter(isActive ? clearPatch : activePatch)}
          >
            <span className="incident-category-count">{count.toLocaleString()}</span>
            <span className="incident-category-label">{label}</span>
          </button>
        );
      })}
    </div>
  );

  const actionRequired = summary.action_required_count;
  const attention = summary.attention_count;
  const flows = summary.flow_groups ?? [];

  if (actionRequired > 0) {
    const criticalFlows = flows.filter((f) => f.signal_type === "action_required").slice(0, 2);
    const topFlow = criticalFlows[0];
    return (
      <div className="incident-card incident-card-critical">
        <div className="incident-card-header">
          🔴 <strong>{actionRequired} critical event{actionRequired === 1 ? "" : "s"} need immediate attention</strong>
        </div>
        <div className="incident-card-subtext muted">
          {filters.signal === "action_required"
            ? "Showing these events below ↓"
            : <button className="incident-card-link" onClick={onSeeAll}>Click to investigate →</button>}
        </div>
        {criticalFlows.map((flow, i) => (
          <div key={i} className="incident-card-flow">
            {flow.subject ? flow.group_title.replace(flow.subject, formatSubject(flow.subject)) : flow.group_title}
          </div>
        ))}
        <div className="incident-card-actions">
          {topFlow ? (
            <button
              className="incident-card-btn-primary"
              onClick={() => onInvestigateActor(topFlow.subject)}
            >
              Investigate top actor →
            </button>
          ) : null}
          <button className="incident-card-btn-secondary" onClick={onSeeAll}>
            See all {actionRequired} events
          </button>
        </div>
        {categoryCards}
      </div>
    );
  }

  if (attention > 0) {
    const attentionFlows = flows.filter((f) => f.signal_type === "attention").slice(0, 2);
    return (
      <div className="incident-card incident-card-attention">
        <div className="incident-card-header">
          🟡 <strong>{attention} event{attention === 1 ? "" : "s"} need review</strong>
        </div>
        {attentionFlows.map((flow, i) => (
          <div key={i} className="incident-card-flow">
            {flow.subject ? flow.group_title.replace(flow.subject, formatSubject(flow.subject)) : flow.group_title}
          </div>
        ))}
        <div className="incident-card-actions">
          <button className="incident-card-btn-secondary" onClick={onSeeAll}>
            Review →
          </button>
        </div>
        {categoryCards}
      </div>
    );
  }

  return (
    <div className="incident-card incident-card-ok">
      <div className="incident-card-header">✅ No critical activity in the {timeWindowLabel}</div>
      {categoryCards}
    </div>
  );
}

// Zone 3: Collapsible filter toolbar
function FilterToolbar({
  filters,
  options,
  filterOpen,
  onToggleFilter,
  onChange,
  onReset,
  groupSimilar,
  onGroupSimilarChange,
}: {
  filters: EventFilters;
  options: FilterOptions | null;
  filterOpen: boolean;
  onToggleFilter: () => void;
  onChange: (filters: EventFilters) => void;
  onReset: () => void;
  groupSimilar: boolean;
  onGroupSimilarChange: (value: boolean) => void;
}) {
  const chips = activeFilterLabels(filters);
  return (
    <div className="filter-toolbar-zone">
      <div className="filter-toolbar-bar">
        <button
          className={`filter-toggle-btn${filterOpen ? " active" : ""}`}
          onClick={onToggleFilter}
          aria-expanded={filterOpen}
        >
          🔍 Filters {filterOpen ? "▲" : "▼"}
        </button>
        {chips.length > 0 ? (
          <div className="filter-active-chips">
            {chips.map((chip) => (
              <span key={chip} className="filter-chip">{chip}</span>
            ))}
          </div>
        ) : null}
        {chips.length > 0 ? (
          <button className="filter-clear-all" onClick={onReset}>
            Clear all
          </button>
        ) : null}
        <label className="group-toggle-label" style={{ marginLeft: "auto" }}>
          <input
            type="checkbox"
            checked={groupSimilar}
            onChange={(e) => onGroupSimilarChange(e.target.checked)}
            aria-label="Group similar events"
          />
          {" "}Group similar
        </label>
      </div>
      {filterOpen ? (
        <FilterBar filters={filters} options={options} onChange={onChange} onReset={onReset} />
      ) : null}
    </div>
  );
}

export default function EventsPage() {
  return (
    <Suspense fallback={<main className="page"><LoadingState label="Loading events" /></main>}>
      <EventsPageInner />
    </Suspense>
  );
}

function EventsPageInner() {
  const router = useRouter();
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
  const tableRef = useRef<HTMLDivElement>(null);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [data, setData] = useState<EventListResponse | null>(null);
  // Session-only toggle: collapse repeated (actor, action, resource) runs into
  // one row. Default OFF preserves the existing list. Not URL-persisted by
  // design — opening a deep link still shows the full feed.
  const [groupSimilar, setGroupSimilar] = useState(false);

  // Actor panel: holds the actor id whose 24h activity panel is open.
  // Seed event lets the panel render the actor's badge / display name
  // immediately while the /summary + /events round-trips complete.
  const [actorPanelId, setActorPanelId] = useState<string | null>(null);
  const [actorPanelSeed, setActorPanelSeed] = useState<AuditEvent | null>(null);

  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);

  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<AuditEvent | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  // Filter panel open by default so controls are visible on first load.
  // URL params still auto-expand it (it was already open), and the user
  // can collapse it with the toggle button if they want less chrome.
  const [filterOpen, setFilterOpen] = useState(true);

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

  // Phase 2 Fix 4: keep `system` fresh on a 30 s heartbeat so the
  // "Last event: …" line at the top of the page reflects ingest health
  // even when the user isn't changing filters. Best-effort — fetch
  // failures are silently ignored; the existing error path on
  // getEvents() owns the top-level error UX.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    async function fetchOnce(signal: AbortSignal) {
      try {
        const fresh = await getSystemStatus(signal);
        if (!cancelled) setSystem(fresh);
      } catch (err) {
        if (isAbortError(err)) return;
        // Silent: do not overwrite system on a transient miss.
      }
    }

    const initial = new AbortController();
    fetchOnce(initial.signal);
    timer = setInterval(() => {
      const c = new AbortController();
      fetchOnce(c.signal);
    }, 30_000);

    return () => {
      cancelled = true;
      initial.abort();
      if (timer !== null) clearInterval(timer);
    };
  }, []);

  const onToggleExpand = (event: AuditEvent) => {
    if (expandedId === event.id) {
      setExpandedId(null);
      setExpandedDetail(null);
      setExpandedError(null);
      setSelectedEvent(null);
      return;
    }
    setExpandedId(event.id);
    setExpandedDetail(null);
    setExpandedError(null);
    setExpandedLoading(true);
    setSelectedEvent(event);
    getEvent(event.id)
      .then((full) => {
        setExpandedDetail(full);
        setSelectedEvent(full);
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setExpandedError(err.message);
      })
      .finally(() => setExpandedLoading(false));
  };

  const handleTriage = async (status: string) => {
    if (!selectedEvent) return;
    const updated = await updateEventTriage(selectedEvent.id, status);
    setSelectedEvent(updated);
    setData((prev) => prev ? { ...prev, items: prev.items.map((e) => e.id === updated.id ? updated : e) } : prev);
  };

  const updateFilters = (next: EventFilters) => {
    setOffset(0);
    setFilters(next);
    setExpandedId(null);
    setExpandedDetail(null);
    // Persist filter state in URL so views are shareable and the back button
    // restores the previous filter set within the session.
    const params = new URLSearchParams();
    for (const key of URL_STRING_KEYS) {
      const value = next[key];
      if (value) params.set(key, value);
    }
    if (next.mode !== "decision") params.set("mode", next.mode);
    router.replace(`?${params.toString()}`, { scroll: false });
  };
  const onActorClick = (event: AuditEvent) => {
    const id = (event.actor_raw_id || event.actor || "").trim();
    if (!id) return;
    setActorPanelSeed(event);
    setActorPanelId(id);
  };
  const closeActorPanel = () => {
    setActorPanelId(null);
    setActorPanelSeed(null);
  };
  const applyActorFilter = (actorId: string) => {
    closeActorPanel();
    updateFilters({ ...filters, actor: actorId });
  };
  const resetFilters = () => updateFilters(defaultFilters);
  const showAllActivity = () => updateFilters(allActivityFilters);
  const applyFlowFilters = (patch: Partial<EventFilters>) => {
    updateFilters({ ...filters, ...patch });
    tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const applyDecisionFilters = (patch: Partial<EventFilters>) => {
    console.log("[Events] applyDecisionFilters — patch:", patch, "tableRef:", tableRef.current);
    updateFilters({ ...filters, ...patch });
    tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const isDecisionMode = filters.mode === "decision";
  const timeWindowLabel = humanTimeWindowLabel(filters.time_window);

  // suppress unused-variable warning for applyFlowFilters / applyDecisionFilters
  void applyFlowFilters;
  void applyDecisionFilters;

  if (error) return <main className="page"><ErrorState message={error} systemState={system?.db_writer_state || system?.consumer_state} /></main>;
  const renderedEvents = data ? data.items : [];

  return (
    <main className="page events-page">
      <StatusStrip
        system={system}
        summary={summary}
        filters={filters}
        onFilterChange={(patch) => updateFilters({ ...filters, ...patch })}
      />
      <IncidentCard
        summary={summary}
        timeWindowLabel={timeWindowLabel}
        filters={filters}
        onCategoryFilter={(patch) => {
          updateFilters({ ...filters, ...patch });
          tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
        onInvestigateActor={(actor) => {
          closeActorPanel();
          updateFilters({ ...filters, actor });
          tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
        onSeeAll={() => {
          updateFilters({ ...filters, signal: "action_required" });
          tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
      />
      <FilterToolbar
        filters={filters}
        options={options}
        filterOpen={filterOpen}
        onToggleFilter={() => setFilterOpen(!filterOpen)}
        onChange={updateFilters}
        onReset={resetFilters}
        groupSimilar={groupSimilar}
        onGroupSimilarChange={setGroupSimilar}
      />
      {summaryLoading ? null : summaryError ? (
        <p className="active-filters">Decision summary unavailable: {summaryError}</p>
      ) : null}
      <div ref={tableRef}>
        {!data ? <LoadingState /> : renderedEvents.length ? (
          <AuditEventTable
            events={renderedEvents}
            groupSimilar={groupSimilar}
            expandedId={expandedId}
            expandedDetail={expandedDetail}
            expandedLoading={expandedLoading}
            expandedError={expandedError}
            onToggleExpand={onToggleExpand}
            onActorClick={onActorClick}
          />
        ) : (
          <EmptyState
            diagnostics={
              isDecisionMode
                ? `No decision events matched this window. Total matching rows: ${data.total}. Switch to audit trail mode to inspect routine reads and informational activity.`
                : `Nothing matched these filters. Total matching rows: ${data.total}.`
            }
            activeFilters={activeFilterLabels(filters)}
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
      </div>
      <RecurringPatterns />
      <ActorActivityPanel
        actorId={actorPanelId}
        seedEvent={actorPanelSeed}
        onClose={closeActorPanel}
        onApplyActorFilter={applyActorFilter}
      />
      <EventDetailDrawer
        event={selectedEvent}
        onClose={() => {
          setSelectedEvent(null);
          setExpandedId(null);
          setExpandedDetail(null);
          setExpandedError(null);
        }}
        onTriage={handleTriage}
      />
    </main>
  );
}
