"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPut, SaveStatus } from "./shared";

type SrStatus = {
  configured: boolean;
  url: string | null;
  subjects: string[];
  error: string | null;
};

type SrTestResult = {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
};

export function SchemaRegistryTab() {
  const [status, setStatus] = useState<SrStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "ok" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<SrTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [removing, setRemoving] = useState(false);

  function loadStatus() {
    setLoading(true);
    setLoadError(null);
    apiGet("/settings/schema_registry/status")
      .then((d) => setStatus(d as SrStatus))
      .catch((e: Error) => setLoadError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadStatus(); }, []);

  async function onSave() {
    setSaveStatus("saving");
    setSaveError(null);
    try {
      await apiPut("/settings/schema_registry/url", { value: url });
      if (apiKey) await apiPut("/settings/schema_registry/api_key", { value: apiKey });
      if (apiSecret) await apiPut("/settings/schema_registry/api_secret", { value: apiSecret });
      setSaveStatus("ok");
      setUrl(""); setApiKey(""); setApiSecret("");
      loadStatus();
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch (e) {
      setSaveStatus("error");
      setSaveError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const r = (await apiPost("/settings/test_sr")) as SrTestResult;
      setTestResult(r);
    } catch (e) {
      setTestResult({ ok: false, latency_ms: null, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }

  async function onRemove() {
    setRemoving(true);
    try {
      await apiDelete("/settings/schema_registry/url");
      await apiDelete("/settings/schema_registry/api_key");
      await apiDelete("/settings/schema_registry/api_secret");
      setTestResult(null);
      loadStatus();
    } catch {
      // best effort
    } finally {
      setRemoving(false);
    }
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (loadError) return <div className="settings-access-denied">Unavailable: {loadError}</div>;

  return (
    <div className="settings-section">
      <div style={{ marginBottom: 12 }}>
        {status?.configured ? (
          <span className="tableflow-badge enabled">CONFIGURED</span>
        ) : (
          <span className="tableflow-badge disabled">NOT CONFIGURED</span>
        )}
      </div>

      {status?.configured ? (
        <>
          <p className="settings-info">
            Schema Registry URL: <code>{status.url}</code>
          </p>
          {status.subjects.length > 0 && (
            <div className="settings-field">
              <label className="settings-label">Registered subjects</label>
              <ul style={{ margin: "4px 0 0 16px", fontSize: "0.85em", color: "var(--muted)" }}>
                {status.subjects.map((s) => <li key={s}>{s}</li>)}
              </ul>
            </div>
          )}
          <div className="settings-actions">
            <button className="settings-test-btn" onClick={onTest} disabled={testing}>
              {testing ? "Testing…" : "Test Connection"}
            </button>
            <button className="settings-test-btn" onClick={onRemove} disabled={removing} style={{ marginLeft: 8 }}>
              {removing ? "Removing…" : "Remove"}
            </button>
          </div>
          {testResult && (
            <div className={`settings-test-result ${testResult.ok ? "ok" : "error"}`}>
              {testResult.ok
                ? `✓ Connected — ${testResult.latency_ms}ms`
                : `✗ ${testResult.error}`}
            </div>
          )}
        </>
      ) : (
        <>
          <p className="settings-info">
            Connect a Confluent Schema Registry to enable Avro serialization for <code>audit.enriched.v1</code> and <code>audit.noise.v1</code>.
            Schema validation ensures downstream consumers always receive well-formed events.
          </p>
          <div className="settings-field">
            <label className="settings-label">Schema Registry URL</label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://psrc-xxxxx.us-east-2.aws.confluent.cloud"
              className="settings-text-input"
            />
          </div>
          <div className="settings-field">
            <label className="settings-label">API Key</label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="SR API key"
              className="settings-text-input"
            />
          </div>
          <div className="settings-field">
            <label className="settings-label">API Secret</label>
            <input
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              placeholder="SR API secret"
              className="settings-text-input"
            />
          </div>
          <div className="settings-actions">
            <button
              className="settings-save-btn"
              onClick={onSave}
              disabled={saveStatus === "saving" || !url}
            >
              {saveStatus === "saving" ? "Saving…" : "Save"}
            </button>
            <SaveStatus status={saveStatus} message={saveError ?? undefined} />
          </div>
        </>
      )}
    </div>
  );
}
