"use client";

import { useEffect, useState } from "react";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import { getAuthAnalytics, isAbortError, type AuthAnalyticsResponse } from "../../lib/api";

type TimeWindow = "1d" | "7d";

function TrendArrow({ trend }: { trend: "up" | "down" | "stable" }) {
  if (trend === "up") return <span style={{ color: "#b54708" }}>↑</span>;
  if (trend === "down") return <span style={{ color: "#0f6e56" }}>↓</span>;
  return <span className="muted">→</span>;
}

export default function AuthAnalyticsPage() {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("1d");
  const [data, setData] = useState<AuthAnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    getAuthAnalytics(timeWindow, controller.signal)
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
  }, [timeWindow]);

  return (
    <main className="page">
      <header style={{ marginBottom: 16 }}>
        <h1>Authentication Analytics</h1>
        <p className="muted">
          Top API keys and source IPs by kafka.Authentication volume.
        </p>
      </header>

      <div className="time-window-pills" style={{ marginBottom: 16 }}>
        {(["1d", "7d"] as const).map((opt) => (
          <button
            key={opt}
            type="button"
            className={`time-window-pill${timeWindow === opt ? " active" : ""}`}
            onClick={() => setTimeWindow(opt)}
          >
            {opt === "1d" ? "Last 24h" : "Last 7d"}
          </button>
        ))}
      </div>

      {loading ? <LoadingState label="Loading authentication analytics" /> : null}
      {error ? <ErrorState message={`Could not load authentication analytics — ${error}`} /> : null}

      {data ? (
        <>
          <section className="panel" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", gap: 24, alignItems: "baseline", flexWrap: "wrap" }}>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Total auth events</div>
                <div style={{ fontSize: 24, fontWeight: 600 }}>{data.total_auth_events.toLocaleString()}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Top 3 actors = % of all auth</div>
                <div style={{ fontSize: 24, fontWeight: 600 }}>{data.concentration.top3_pct}%</div>
              </div>
            </div>
          </section>

          <section className="panel table-panel" style={{ marginBottom: 16 }}>
            <h2 style={{ marginTop: 0 }}>Top API Keys by Auth Volume</h2>
            {data.top_actors.length === 0 ? (
              <p className="muted">No authentication events in this window.</p>
            ) : (
              <table className="event-table">
                <thead>
                  <tr>
                    <th>Actor</th>
                    <th>Display Name</th>
                    <th style={{ textAlign: "right" }}>Auth Count</th>
                    <th style={{ textAlign: "right" }}>Unique IPs</th>
                    <th style={{ textAlign: "right" }}>% of Total</th>
                    <th>Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_actors.map((row) => (
                    <tr key={row.actor}>
                      <td><code>{row.actor}</code></td>
                      <td>{row.actor_display_name === row.actor ? <span className="muted">—</span> : row.actor_display_name}</td>
                      <td style={{ textAlign: "right" }}>{row.auth_count.toLocaleString()}</td>
                      <td style={{ textAlign: "right" }}>{row.unique_ips.toLocaleString()}</td>
                      <td style={{ textAlign: "right" }}>{row.pct_of_total}%</td>
                      <td><TrendArrow trend={row.trend} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="panel table-panel">
            <h2 style={{ marginTop: 0 }}>Top Source IPs</h2>
            {data.top_source_ips.length === 0 ? (
              <p className="muted">No source IP data in this window.</p>
            ) : (
              <table className="event-table">
                <thead>
                  <tr>
                    <th>IP Address</th>
                    <th style={{ textAlign: "right" }}>Auth Count</th>
                    <th style={{ textAlign: "right" }}>Unique Actors</th>
                    <th>Cloud Provider</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_source_ips.map((row) => (
                    <tr key={row.source_ip}>
                      <td><code>{row.source_ip}</code></td>
                      <td style={{ textAlign: "right" }}>{row.auth_count.toLocaleString()}</td>
                      <td style={{ textAlign: "right" }}>{row.unique_actors.toLocaleString()}</td>
                      <td>{row.cloud_provider}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
