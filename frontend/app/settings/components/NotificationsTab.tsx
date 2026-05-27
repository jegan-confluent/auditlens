"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getNotificationDestinations,
  testNotification,
  toggleNotificationDestination,
  type NotificationDestinationView,
  type NotificationDestinationsResponse,
  type NotificationTestResponse,
} from "../../../lib/api";

function describeFilters(filters: NotificationDestinationView["filters"]): string {
  const parts: string[] = [];
  if (filters.signal_type.length > 0) parts.push(`signal: ${filters.signal_type.join(", ")}`);
  if (filters.min_risk_level) parts.push(`min risk: ${filters.min_risk_level}`);
  if (filters.action_category.length > 0) parts.push(`categories: ${filters.action_category.join(", ")}`);
  if (filters.exclude_actions.length > 0) parts.push(`excl: ${filters.exclude_actions.length} action(s)`);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function modeLabel(d: NotificationDestinationView): string {
  if (d.mode === "digest") return `digest @ ${d.digest_schedule} UTC`;
  return "realtime";
}

function StatusBanner({ status, configPath }: { status: NotificationDestinationsResponse["status"]; configPath: string }) {
  if (status === "ok") return null;
  if (status === "no_config") {
    return (
      <p className="settings-info">
        No notification destinations configured. Create <code>{configPath}</code> (copy from <code>notifications.example.yml</code>)
        and mount it into the api container to add Slack, PagerDuty, Teams, or webhook destinations.
      </p>
    );
  }
  if (status === "no_destinations") {
    return (
      <p className="settings-info">
        <code>{configPath}</code> exists but has no <code>destinations</code> array. Edit the file and restart the forwarder.
      </p>
    );
  }
  return (
    <p className="settings-access-denied">
      Could not parse <code>{configPath}</code>. Check YAML syntax in the forwarder logs.
    </p>
  );
}

export function NotificationsTab() {
  const [data, setData] = useState<NotificationDestinationsResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [togglingName, setTogglingName] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<NotificationTestResponse | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadError(null);
    try {
      const next = await getNotificationDestinations(signal);
      setData(next);
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function handleToggle(name: string) {
    setTogglingName(name);
    setToggleError(null);
    try {
      await toggleNotificationDestination(name);
      await load();
    } catch (e) {
      setToggleError(e instanceof Error ? e.message : String(e));
    } finally {
      setTogglingName(null);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const result = await testNotification();
      setTestResult(result);
    } catch (e) {
      setTestError(e instanceof Error ? e.message : String(e));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="settings-section">
      <p className="settings-info">
        Notification destinations are configured in <code>notifications.yml</code> on the server.
        Webhook URLs and integration keys stay on disk — they are never returned by the API.
        Supported types: <strong>Slack</strong>, <strong>Microsoft Teams</strong>, <strong>generic webhooks</strong>, <strong>PagerDuty</strong>.
      </p>
      {loadError !== null ? (
        <p className="settings-access-denied">Could not load destinations: {loadError}</p>
      ) : data === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <StatusBanner status={data.status} configPath={data.config_path} />
          {data.destinations.length > 0 ? (
            <table className="settings-table" style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Name</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Type</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Mode</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Rate/min</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Filters</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Enabled</th>
                </tr>
              </thead>
              <tbody>
                {data.destinations.map((d) => (
                  <tr key={d.name} style={{ borderTop: "1px solid var(--border, #2a2a2a)" }}>
                    <td style={{ padding: "6px 8px" }}><strong>{d.name}</strong></td>
                    <td style={{ padding: "6px 8px" }}>{d.type}</td>
                    <td style={{ padding: "6px 8px" }}>{modeLabel(d)}</td>
                    <td style={{ padding: "6px 8px" }}>
                      {d.rate_limit_per_minute === 0 ? "∞" : d.rate_limit_per_minute}
                    </td>
                    <td style={{ padding: "6px 8px", fontSize: "0.85em", color: "var(--muted)" }}>
                      {describeFilters(d.filters)}
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <button
                        className="settings-test-btn"
                        onClick={() => { void handleToggle(d.name); }}
                        disabled={togglingName !== null}
                        aria-label={`Toggle ${d.name} (currently ${d.enabled ? "enabled" : "disabled"})`}
                      >
                        {togglingName === d.name ? "…" : d.enabled ? "✓ Enabled" : "Disabled"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {toggleError !== null ? (
            <p className="settings-access-denied" style={{ marginTop: 8 }}>Toggle failed: {toggleError}</p>
          ) : null}
        </>
      )}
      <div style={{ marginTop: 16 }}>
        <button
          className="settings-test-btn"
          onClick={() => { void handleTest(); }}
          disabled={testing}
        >
          {testing ? "Testing…" : "Send test notification"}
        </button>
      </div>
      {testError !== null && (
        <p className="settings-access-denied" style={{ marginTop: 8 }}>
          ✗ {testError}
        </p>
      )}
      {testResult !== null && (
        <div style={{ marginTop: 10 }}>
          {testResult.warning ? (
            <p className="settings-info" style={{ marginBottom: 8 }}>ℹ {testResult.warning}</p>
          ) : (
            <p className="settings-info" style={{ marginBottom: 8 }}>
              <strong>Sent: {testResult.sent_count}</strong>
              {testResult.error_count > 0 && (
                <> · <span style={{ color: "var(--critical)" }}>Errors: {testResult.error_count}</span></>
              )}
            </p>
          )}
          {testResult.results.length > 0 && (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, fontFamily: "var(--font-mono)", fontSize: "0.9em" }}>
              {testResult.results.map((r) => {
                let icon = "?";
                let toneColor: string = "var(--muted)";
                if (r.status === "sent") { icon = "✅"; toneColor = "var(--success)"; }
                else if (r.status === "skipped") { icon = "⏭"; toneColor = "var(--muted)"; }
                else if (r.status === "error") { icon = "❌"; toneColor = "var(--critical)"; }
                return (
                  <li key={r.destination} style={{ padding: "2px 0", color: toneColor }}>
                    {icon} <strong style={{ color: "var(--text)" }}>{r.destination}</strong>
                    {r.type && <span style={{ color: "var(--muted)" }}> ({r.type})</span>}
                    {r.status === "sent" && <> — delivered</>}
                    {r.status === "skipped" && r.reason && <> — {r.reason}</>}
                    {r.status === "error" && r.error && <> — {r.error}</>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
