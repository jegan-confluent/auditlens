"use client";

import { useEffect, useState } from "react";
import { type ResourceCatalogItem, getResourceCatalog } from "../../../lib/api";

const TYPE_COLORS: Record<string, string> = {
  kafka_cluster: "#0F6E56",
  connector: "#BA7517",
  schema_registry: "#7B4FC0",
  flink: "#1D6FCC",
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function ResourceCatalogTab() {
  const [items, setItems] = useState<ResourceCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    getResourceCatalog({ limit: 200 })
      .then(setItems)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const types = Array.from(new Set(items.map((i) => i.resource_type))).sort();

  const filtered = items.filter((i) => {
    if (typeFilter && i.resource_type !== typeFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        i.resource_id.toLowerCase().includes(q) ||
        i.resource_name.toLowerCase().includes(q) ||
        (i.display_name ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Error: {error}</div>;

  return (
    <div className="settings-section">
      <div className="resource-catalog-filters">
        <input
          className="settings-text-input"
          placeholder="Search by ID or name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 180 }}
        />
        <select
          className="settings-text-input"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{ width: 180 }}
        >
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="muted" style={{ marginTop: 16 }}>
          {items.length === 0
            ? "No resources catalogued yet. Events will populate this automatically."
            : "No resources match your filter."}
        </p>
      ) : (
        <table className="actor-map-table resource-catalog-table">
          <thead>
            <tr>
              <th>Resource ID</th>
              <th>Type</th>
              <th>Name</th>
              <th>Environment</th>
              <th>First Seen</th>
              <th>Last Seen</th>
              <th className="resource-count-col">Events</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => {
              const typeColor = TYPE_COLORS[item.resource_type] ?? "#5F5E5A";
              return (
                <tr key={item.resource_id}>
                  <td><code className="resource-id">{item.resource_id}</code></td>
                  <td>
                    <span className="resource-type-pill" style={{ background: typeColor }}>
                      {item.resource_type}
                    </span>
                  </td>
                  <td>{item.display_name || item.resource_name || "—"}</td>
                  <td className="muted">{item.environment_name || item.environment_id || "—"}</td>
                  <td className="muted" title={item.first_seen}>{relativeTime(item.first_seen)}</td>
                  <td className="muted" title={item.last_seen}>{relativeTime(item.last_seen)}</td>
                  <td className="resource-count-col">{item.event_count.toLocaleString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
