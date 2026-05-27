"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPut, SaveStatus } from "./shared";

type SrSubject = {
  name: string;
  schema_id: number | null;
  version: number | null;
};

type SrStatus = {
  configured: boolean;
  url: string | null;
  subjects: SrSubject[];
  error: string | null;
  drift_detected?: boolean;
  drift_detail?: string | null;
};

type SrTestResult = {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
};

type RegisterResult = {
  subject: string;
  status: "registered" | "skipped" | "updated" | "error";
  schema_id: number | null;
  version: number | null;
  previous_version: number | null;
  compatibility: string | null;
  error: string | null;
};

type RegisterResponse = {
  results: RegisterResult[];
  success: boolean;
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
  const [registering, setRegistering] = useState(false);
  const [registerResults, setRegisterResults] = useState<RegisterResult[] | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);

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
      setRegisterResults(null);
      loadStatus();
    } catch {
      // best effort
    } finally {
      setRemoving(false);
    }
  }

  async function onRegister() {
    setRegistering(true);
    setRegisterError(null);
    setRegisterResults(null);
    try {
      const r = (await apiPost("/settings/schema_registry/register")) as RegisterResponse;
      setRegisterResults(r.results);
      // Re-fetch status so subject versions reflect the new registrations.
      loadStatus();
    } catch (e) {
      setRegisterError(e instanceof Error ? e.message : String(e));
    } finally {
      setRegistering(false);
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
          {status.drift_detected && (
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--warning)",
                color: "var(--warning)",
                padding: "8px 12px",
                borderRadius: 6,
                margin: "10px 0",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                fontSize: "0.9em",
              }}
            >
              <span>
                ⚠ {status.drift_detail ?? "Local schema differs from registered version."}
              </span>
              <button
                className="settings-save-btn"
                onClick={onRegister}
                disabled={registering}
                style={{ flex: "0 0 auto" }}
              >
                {registering ? "Registering…" : "Register schemas →"}
              </button>
            </div>
          )}
          {status.subjects.length > 0 && (
            <div className="settings-field">
              <label className="settings-label">Registered subjects</label>
              <table style={{ marginTop: 6, fontSize: "0.85em", borderCollapse: "collapse", width: "100%", maxWidth: 540 }}>
                <thead>
                  <tr style={{ color: "var(--muted)", textAlign: "left" }}>
                    <th style={{ padding: "4px 8px", borderBottom: "1px solid var(--border)" }}>Subject</th>
                    <th style={{ padding: "4px 8px", borderBottom: "1px solid var(--border)", width: 80 }}>Version</th>
                    <th style={{ padding: "4px 8px", borderBottom: "1px solid var(--border)", width: 100 }}>Schema ID</th>
                  </tr>
                </thead>
                <tbody>
                  {status.subjects.map((s) => (
                    <tr key={s.name}>
                      <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)" }}>{s.name}</td>
                      <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)", color: "var(--muted)" }}>
                        {s.version != null ? `v${s.version}` : "—"}
                      </td>
                      <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)", color: "var(--muted)" }}>
                        {s.schema_id != null ? s.schema_id : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="settings-actions">
            <button className="settings-test-btn" onClick={onTest} disabled={testing}>
              {testing ? "Testing…" : "Test Connection"}
            </button>
            <button
              className="settings-save-btn"
              onClick={onRegister}
              disabled={registering}
              style={{ marginLeft: 8 }}
              title="Register the AuditLens Avro schemas (audit.enriched.v1-value + signals + alerts + dlq). Required after first SR setup and after editing any .avsc file."
            >
              {registering ? "Registering…" : "Register schemas"}
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
          {registerError && (
            <div className="settings-test-result error">✗ {registerError}</div>
          )}
          {registerResults && (
            <div style={{ marginTop: 10, fontSize: "0.9em" }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Registration result</div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {registerResults.map((r) => (
                  <li key={r.subject} style={{ padding: "2px 0", fontFamily: "var(--font-mono)" }}>
                    {r.status === "registered" && (
                      <span>✅ <strong>{r.subject}</strong> registered (id={r.schema_id}, version={r.version})
                        {r.compatibility && <span style={{ color: "var(--muted)" }}> · compat {r.compatibility}</span>}
                      </span>
                    )}
                    {r.status === "updated" && (
                      <span>🔄 <strong>{r.subject}</strong> updated (v{r.previous_version} → v{r.version}, id={r.schema_id})
                        {r.compatibility && <span style={{ color: "var(--muted)" }}> · compat {r.compatibility}</span>}
                      </span>
                    )}
                    {r.status === "skipped" && (
                      <span>⏭ <strong>{r.subject}</strong> already at version {r.version} (skipped)
                        {r.compatibility && <span style={{ color: "var(--muted)" }}> · compat {r.compatibility}</span>}
                      </span>
                    )}
                    {r.status === "error" && (
                      <span style={{ color: "var(--critical)" }}>❌ <strong>{r.subject}</strong> error: {r.error}</span>
                    )}
                  </li>
                ))}
              </ul>
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
