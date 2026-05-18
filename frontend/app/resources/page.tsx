"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import { type ResourceCatalogItem, type ResourceCatalogResponse, getResourceCatalogPage, isAbortError } from "../../lib/api";

const TYPE_COLORS: Record<string, string> = {
  topic: "#1d6fcc",
  environment: "#0f6e56",
  cluster: "#7b4fc0",
  serviceaccount: "#ba7517",
  apikey: "#c47900",
};

function typeBadgeStyle(resourceType: string): React.CSSProperties {
  const color = TYPE_COLORS[resourceType.toLowerCase()] ?? "#5f5e5a";
  return { background: color };
}

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

export default function ResourceCatalogPage() {
  const router = useRouter();
  const [data, setData] = useState<ResourceCatalogResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("All");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getResourceCatalogPage({ limit: 500 }, controller.signal)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (isAbortError(err)) return;
        setError(err.message);
        setLoading(false);
      });
    return () => controller.abort();
  }, [retryKey]);

  const types = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.items.map((i) => i.resource_type))).sort();
  }, [data]);

  const filtered = useMemo<ResourceCatalogItem[]>(() => {
    if (!data) return [];
    return data.items.filter((item) => {
      if (typeFilter !== "All" && item.resource_type !== typeFilter) return false;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        return (
          item.resource_id.toLowerCase().includes(q) ||
          item.resource_name.toLowerCase().includes(q) ||
          (item.display_name ?? "").toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [data, typeFilter, search]);

  function handleRowClick(item: ResourceCatalogItem): void {
    router.push(`/events?resource=${encodeURIComponent(item.resource_name)}`);
  }

  if (loading) {
    return (
      <main className="page">
        <LoadingState label="Loading resource catalog" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="page">
        <ErrorState message={`Could not load resource catalog — ${error}`} />
        <div style={{ marginTop: 12 }}>
          <button className="btn-secondary" onClick={() => setRetryKey((k) => k + 1)}>
            Retry
          </button>
        </div>
      </main>
    );
  }

  const typeCount = types.length;
  const total = data?.total ?? 0;

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Resource Catalog</h1>
          {total > 0 && (
            <p className="page-subtitle muted">
              {total} resource{total !== 1 ? "s" : ""} across {typeCount} type{typeCount !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        <input
          className="search-input"
          type="search"
          placeholder="Search by name or ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search resources"
        />
      </div>

      <div className="filter-pills" role="group" aria-label="Filter by resource type">
        {["All", ...types].map((t) => (
          <button
            key={t}
            type="button"
            className={`filter-pill${typeFilter === t ? " active" : ""}`}
            onClick={() => setTypeFilter(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="panel empty-state">
          {total === 0
            ? "No resources found. Events will appear here once the forwarder processes audit log data."
            : "No resources match your current filters."}
        </div>
      ) : (
        <div className="panel">
          <table className="events-table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Type</th>
                <th>Events</th>
                <th>Last seen</th>
                <th>First seen</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr
                  key={item.resource_id}
                  onClick={() => handleRowClick(item)}
                  style={{ cursor: "pointer" }}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && handleRowClick(item)}
                  aria-label={`${item.resource_name} — click to view events`}
                >
                  <td>
                    <span className="font-medium">
                      {item.display_name || item.resource_name}
                    </span>
                    {item.display_name && item.display_name !== item.resource_name && (
                      <span className="muted" style={{ marginLeft: 6, fontSize: "0.85em" }}>
                        {item.resource_name}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className="resource-type-pill" style={typeBadgeStyle(item.resource_type)}>
                      {item.resource_type}
                    </span>
                  </td>
                  <td>{item.event_count.toLocaleString()}</td>
                  <td className="muted" title={item.last_seen}>
                    {relativeTime(item.last_seen)}
                  </td>
                  <td className="muted" title={item.first_seen}>
                    {relativeTime(item.first_seen)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
