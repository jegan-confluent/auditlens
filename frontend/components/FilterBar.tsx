"use client";

import { useEffect, useRef, useState } from "react";
import type { FilterOptions } from "../lib/types";
import { activeFilterLabels, applyQuickFilter, type EventFilters } from "../lib/eventFilters";
export { activeFilterLabels, defaultFilters, type EventFilters } from "../lib/eventFilters";

const ACTOR_DEBOUNCE_MS = 300;

const quickFilters: Array<{ label: string; patch: Partial<EventFilters> }> = [
  { label: "Needs Attention 🔴", patch: { mode: "decision", signal: "action_required,attention", hide_noise: "true", time_window: "24h" } },
  { label: "Decision mode", patch: { mode: "decision", time_window: "24h", signal: "", hide_noise: "false", impact_type: "" } },
  { label: "Show full audit trail", patch: { mode: "audit_trail", time_window: "7d", signal: "", hide_noise: "false", impact_type: "" } },
  { label: "Action Needed", patch: { mode: "decision", signal: "action_required", hide_noise: "true" } },
  { label: "Review", patch: { mode: "decision", signal: "attention", hide_noise: "true" } },
  { label: "Hide Noise", patch: { mode: "decision", hide_noise: "true", signal: "" } },
  { label: "Show Noise", patch: { mode: "audit_trail", hide_noise: "false", signal: "" } },
  { label: "Failed/Denied", patch: { mode: "decision", result: "Failure", hide_noise: "false" } },
  { label: "Destructive", patch: { mode: "decision", impact_type: "destructive", hide_noise: "false" } },
  { label: "Config Changes", patch: { mode: "decision", impact_type: "configuration_change", hide_noise: "false" } },
  { label: "Access Changes", patch: { mode: "decision", impact_type: "access_change", hide_noise: "false" } }
];

const SIGNAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All" },
  { value: "action_required", label: "🔴 Action Required" },
  { value: "attention", label: "🟡 Review" },
  { value: "informational", label: "ℹ️ Info" },
  { value: "noise", label: "🔇 Noise" }
];

// Dropdown values are sent verbatim to paramsFromFilters which routes them to
// the right backend param (result=Failure, is_denied=true, etc). The DB
// stores result in {Success, Failure}; "Denied" maps to is_denied=true.
const RESULT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "All results" },
  { value: "Success", label: "Success" },
  { value: "Failure", label: "Failure" },
  { value: "Denied", label: "Denied" }
];

function isQuickFilterActive(filters: EventFilters, patch: Partial<EventFilters>) {
  return Object.entries(patch).every(([key, value]) => filters[key as keyof EventFilters] === value);
}

export default function FilterBar({ filters, options, onChange, onReset }: {
  filters: EventFilters;
  options: FilterOptions | null;
  onChange: (filters: EventFilters) => void;
  onReset: () => void;
}) {
  const update = (key: keyof EventFilters, value: string) => onChange({ ...filters, [key]: value });
  const apply = (patch: Partial<EventFilters>) => onChange(applyQuickFilter(filters, patch));
  const activeLabels = activeFilterLabels(filters);

  const secondaryCount = [
    filters.actor,
    filters.resource,
    filters.cluster_name,
    filters.environment_name,
    filters.resource_type,
    filters.result,
  ].filter(Boolean).length;

  const [moreOpen, setMoreOpen] = useState(
    () => [filters.actor, filters.resource, filters.cluster_name, filters.environment_name, filters.resource_type, filters.result].some(Boolean)
  );

  // Debounced actor search: keep an internal draft so each keystroke doesn't
  // refetch /events. The committed `filters.actor` still drives the URL /
  // chips / param plumbing; we just delay the publish by ACTOR_DEBOUNCE_MS.
  const [actorDraft, setActorDraft] = useState(filters.actor);
  const actorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep the draft in sync when the parent resets filters (e.g. "Clear all"
  // button or a quick-filter chip that wipes actor). Compare values rather
  // than refs so we don't fight the user's own typing.
  useEffect(() => {
    setActorDraft(filters.actor);
  }, [filters.actor]);

  const commitActor = (value: string) => {
    if (actorTimer.current) clearTimeout(actorTimer.current);
    actorTimer.current = setTimeout(() => {
      onChange({ ...filters, actor: value });
    }, ACTOR_DEBOUNCE_MS);
  };
  const onActorInput = (value: string) => {
    setActorDraft(value);
    commitActor(value);
  };
  const onActorClear = () => {
    if (actorTimer.current) clearTimeout(actorTimer.current);
    setActorDraft("");
    onChange({ ...filters, actor: "" });
  };

  return (
    <section className="filter-panel">
      <div className="quick-filter-row" aria-label="Quick filters">
        {quickFilters.map((filter) => (
          <button
            key={filter.label}
            className={`quick-filter ${isQuickFilterActive(filters, filter.patch) ? "active" : ""}`}
            onClick={() => apply(filter.patch)}
          >
            {filter.label}
          </button>
        ))}
        <button className="quick-filter reset" onClick={onReset}>Clear Filters</button>
      </div>

      <div className="filter-primary-row">
        <div className="signal-pills" role="group" aria-label="Signal filter">
          {SIGNAL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`signal-pill${filters.signal === opt.value ? " active" : ""}`}
              onClick={() => update("signal", opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <select
          value={filters.time_window}
          onChange={(e) => update("time_window", e.target.value)}
          aria-label="Time window"
        >
          <option value="30m">Last 30 min</option>
          <option value="2h">Last 2h</option>
          <option value="4h">Last 4h</option>
          <option value="12h">Last 12h</option>
          <option value="24h">Last 24h</option>
          <option value="7d">Last 7d</option>
          <option value="30d">Last 30d</option>
        </select>
        <select
          value={filters.action_category}
          onChange={(e) => update("action_category", e.target.value)}
          aria-label="Action category"
        >
          <option value="">All actions</option>
          {(options?.action_categories || []).map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        <button
          type="button"
          className={`more-filters-btn${moreOpen ? " active" : ""}`}
          onClick={() => setMoreOpen(!moreOpen)}
          aria-expanded={moreOpen}
        >
          {moreOpen
            ? "Hide filters"
            : secondaryCount > 0
            ? `More filters (${secondaryCount})`
            : "More filters"}
        </button>
      </div>

      {moreOpen ? (
        <div className="filter-secondary-panel">
          <span className="actor-search">
            <input
              value={actorDraft}
              onChange={(e) => onActorInput(e.target.value)}
              placeholder="Filter by actor name or ID..."
              aria-label="Actor filter"
            />
            {actorDraft ? (
              <button type="button" className="actor-search-clear" aria-label="Clear actor filter" onClick={onActorClear}>×</button>
            ) : null}
          </span>
          <input
            value={filters.resource}
            onChange={(e) => update("resource", e.target.value)}
            placeholder="Resource text"
            aria-label="Resource search"
          />
          <select
            value={filters.resource_type}
            onChange={(e) => update("resource_type", e.target.value)}
            aria-label="Resource type"
          >
            <option value="">All resource types</option>
            {(options?.resource_types || []).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <input
            value={filters.cluster_name}
            onChange={(e) => update("cluster_name", e.target.value)}
            placeholder="Cluster"
            aria-label="Cluster filter"
          />
          <select
            value={filters.environment_name}
            onChange={(e) => update("environment_name", e.target.value)}
            aria-label="Environment filter"
          >
            <option value="">All environments</option>
            {(options?.environments || []).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <select
            value={filters.result}
            onChange={(e) => update("result", e.target.value)}
            aria-label="Result"
          >
            {RESULT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      ) : null}

      <p className="active-filters">Active filters: {activeLabels.length ? activeLabels.join(", ") : "none"}</p>
    </section>
  );
}
