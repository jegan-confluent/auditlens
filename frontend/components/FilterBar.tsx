"use client";

import type { FilterOptions } from "../lib/types";
import { activeFilterLabels, applyQuickFilter, type EventFilters } from "../lib/eventFilters";
export { activeFilterLabels, defaultFilters, type EventFilters } from "../lib/eventFilters";

const quickFilters: Array<{ label: string; patch: Partial<EventFilters> }> = [
  { label: "Decision mode", patch: { mode: "decision", time_window: "2h", signal: "", hide_noise: "false", impact_type: "" } },
  { label: "Show full audit trail", patch: { mode: "audit_trail", time_window: "72h", signal: "", hide_noise: "false", impact_type: "" } },
  { label: "Action Needed", patch: { mode: "decision", signal: "action_required", hide_noise: "true" } },
  { label: "Review", patch: { mode: "decision", signal: "attention", hide_noise: "true" } },
  { label: "Hide Noise", patch: { mode: "decision", hide_noise: "true", signal: "" } },
  { label: "Show Noise", patch: { mode: "audit_trail", hide_noise: "false", signal: "" } },
  { label: "Failed/Denied", patch: { mode: "decision", result: "Failure", hide_noise: "false" } },
  { label: "Destructive", patch: { mode: "decision", impact_type: "destructive", hide_noise: "false" } },
  { label: "Config Changes", patch: { mode: "decision", impact_type: "configuration_change", hide_noise: "false" } },
  { label: "Access Changes", patch: { mode: "decision", impact_type: "access_change", hide_noise: "false" } }
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
        <select value={filters.time_window} onChange={(event) => update("time_window", event.target.value)} aria-label="Time window">
          <option value="10m">Last 10 mins</option>
          <option value="1h">Last hour</option>
          <option value="2h">Last 2 hours</option>
          <option value="24h">Last 24 hours</option>
          <option value="72h">Last 72 hours</option>
        </select>
        <select value={filters.resource_type} onChange={(event) => update("resource_type", event.target.value)}>
          <option value="">All resource types</option>
          {(options?.resource_types || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <input value={filters.resource} onChange={(event) => update("resource", event.target.value)} placeholder="Resource text" />
        <select value={filters.action_category} onChange={(event) => update("action_category", event.target.value)}>
          <option value="">All actions</option>
          {(options?.action_categories || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <input value={filters.actor} onChange={(event) => update("actor", event.target.value)} placeholder="Actor" />
        <select value={filters.result} onChange={(event) => update("result", event.target.value)}>
          <option value="">All results</option>
          {(options?.results || []).map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </div>
      <p className="active-filters">Active filters: {activeLabels.length ? activeLabels.join(", ") : "none"}</p>
    </section>
  );
}
