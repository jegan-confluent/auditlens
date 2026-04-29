"use client";

import type { FilterOptions } from "../lib/types";

export type EventFilters = {
  time_window: string;
  resource_type: string;
  resource: string;
  action_category: string;
  actor: string;
  result: string;
};

const defaultFilters: EventFilters = {
  time_window: "72h",
  resource_type: "",
  resource: "",
  action_category: "",
  actor: "",
  result: ""
};

export { defaultFilters };

export default function FilterBar({ filters, options, onChange, onReset }: {
  filters: EventFilters;
  options: FilterOptions | null;
  onChange: (filters: EventFilters) => void;
  onReset: () => void;
}) {
  const update = (key: keyof EventFilters, value: string) => onChange({ ...filters, [key]: value });
  return (
    <>
      <div className="toolbar">
        <input value={filters.time_window} onChange={(event) => update("time_window", event.target.value)} placeholder="72h" />
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
        <button onClick={onReset}>Reset filters</button>
      </div>
      <p className="muted">Active filters: {Object.entries(filters).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`).join(", ") || "none"}</p>
    </>
  );
}
