"use client";

import type { FilterOptions } from "../lib/types";
import { activeFilterLabels, applyQuickFilter, type EventFilters } from "../lib/eventFilters";
export { activeFilterLabels, defaultFilters, type EventFilters } from "../lib/eventFilters";

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
  { value: "", label: "All signals" },
  { value: "action_required", label: "🔴 Action Required" },
  { value: "attention", label: "🟡 Needs Review" },
  { value: "informational", label: "ℹ️ Informational" },
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
      <div className="toolbar filter-toolbar">
        <select value={filters.signal} onChange={(event) => update("signal", event.target.value)} aria-label="Signal type">
          {SIGNAL_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <select value={filters.time_window} onChange={(event) => update("time_window", event.target.value)} aria-label="Time window">
          <option value="1h">Last hour</option>
          <option value="6h">Last 6 hours</option>
          <option value="12h">Last 12 hours</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </select>
        <select value={filters.resource_type} onChange={(event) => update("resource_type", event.target.value)} aria-label="Resource type">
          <option value="">All resource types</option>
          {(options?.resource_types || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <input value={filters.resource} onChange={(event) => update("resource", event.target.value)} placeholder="Resource text" aria-label="Resource search" />
        <input value={filters.cluster_name} onChange={(event) => update("cluster_name", event.target.value)} placeholder="Cluster" aria-label="Cluster filter" />
        <input value={filters.environment_name} onChange={(event) => update("environment_name", event.target.value)} placeholder="Environment" aria-label="Environment filter" />
        <select value={filters.action_category} onChange={(event) => update("action_category", event.target.value)} aria-label="Action category">
          <option value="">All actions</option>
          {(options?.action_categories || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <input value={filters.actor} onChange={(event) => update("actor", event.target.value)} placeholder="Actor" aria-label="Actor filter" />
        <select value={filters.result} onChange={(event) => update("result", event.target.value)} aria-label="Result">
          {RESULT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      <p className="active-filters">Active filters: {activeLabels.length ? activeLabels.join(", ") : "none"}</p>
    </section>
  );
}
