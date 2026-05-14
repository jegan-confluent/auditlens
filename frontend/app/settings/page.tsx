"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost/api";

type SettingEntry = {
  is_secret: boolean;
  is_set: boolean;
  masked: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

type SettingsCategory = Record<string, SettingEntry>;

async function apiGet(path: string): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function apiPut(path: string, body: object): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function apiPost(path: string, body: object = {}): Promise<unknown> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function useSetting(category: string): { data: SettingsCategory | null; loading: boolean; error: string | null; reload: () => void } {
  const [data, setData] = useState<SettingsCategory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = () => setTick((t) => t + 1);
  useEffect(() => {
    setLoading(true);
    apiGet(`/settings/${category}`)
      .then((d) => { setData(d as SettingsCategory); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [category, tick]);
  return { data, loading, error, reload };
}

function SaveStatus({ status, message }: { status: "idle" | "saving" | "ok" | "error"; message?: string }) {
  if (status === "idle") return null;
  if (status === "saving") return <span className="settings-save-status saving">Saving…</span>;
  if (status === "ok") return <span className="settings-save-status ok">Saved ✓</span>;
  return <span className="settings-save-status error">Error: {message}</span>;
}

// ── Retention Tab ─────────────────────────────────────────────────────────────
function RetentionTab() {
  const { data, loading, error, reload } = useSetting("retention");
  const [eventDays, setEventDays] = useState("7");
  const [rawDays, setRawDays] = useState("7");
  const [noiseDays, setNoiseDays] = useState("3");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "ok" | "error">("idle");

  useEffect(() => {
    if (!data) return;
    if (data.event_retention_days?.masked) setEventDays(data.event_retention_days.masked);
    if (data.raw_payload_retention_days?.masked) setRawDays(data.raw_payload_retention_days.masked);
    if (data.noise_retention_days?.masked) setNoiseDays(data.noise_retention_days.masked);
  }, [data]);

  async function onSave() {
    setSaveStatus("saving");
    try {
      await apiPut("/settings/retention/event_retention_days", { value: eventDays });
      await apiPut("/settings/retention/raw_payload_retention_days", { value: rawDays });
      await apiPut("/settings/retention/noise_retention_days", { value: noiseDays });
      setSaveStatus("ok");
      reload();
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch {
      setSaveStatus("error");
    }
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Unavailable: {error}</div>;

  return (
    <div className="settings-section">
      <div className="settings-field">
        <label className="settings-label">Event retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={eventDays} onChange={(e) => setEventDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label">Raw payload retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={rawDays} onChange={(e) => setRawDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label">Noise retention</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={noiseDays} onChange={(e) => setNoiseDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      <p className="settings-info">
        Raw payload retention removes original Confluent event JSON. Enriched fields are always kept for the full event retention period.
      </p>
      <div className="settings-actions">
        <button className="settings-save-btn" onClick={onSave} disabled={saveStatus === "saving"}>Save</button>
        <SaveStatus status={saveStatus} />
      </div>
    </div>
  );
}

// ── Cold Storage Tab ──────────────────────────────────────────────────────────
function ColdStorageTab() {
  const { data, loading, error, reload } = useSetting("cold_storage");
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("s3");
  const [bucket, setBucket] = useState("");
  const [prefix, setPrefix] = useState("auditlens/");
  const [afterDays, setAfterDays] = useState("7");
  const [region, setRegion] = useState("us-east-1");
  const [accessKey, setAccessKey] = useState("");
  const [secretKeyNew, setSecretKeyNew] = useState("");
  const [editSecret, setEditSecret] = useState(false);
  const [editGcs, setEditGcs] = useState(false);
  const [gcsCredsNew, setGcsCredsNew] = useState("");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "ok" | "error">("idle");
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const secretIsSet = data?.aws_secret_key?.is_set ?? false;
  const gcsIsSet = data?.gcs_credentials?.is_set ?? false;

  useEffect(() => {
    if (!data) return;
    if (data.enabled?.masked) setEnabled(data.enabled.masked === "true");
    if (data.provider?.masked) setProvider(data.provider.masked);
    if (data.bucket?.masked) setBucket(data.bucket.masked ?? "");
    if (data.prefix?.masked) setPrefix(data.prefix.masked ?? "auditlens/");
    if (data.after_days?.masked) setAfterDays(data.after_days.masked ?? "7");
    if (data.aws_region?.masked) setRegion(data.aws_region.masked ?? "us-east-1");
    if (data.aws_access_key?.masked) setAccessKey(data.aws_access_key.masked ?? "");
  }, [data]);

  async function onSave() {
    setSaveStatus("saving");
    try {
      await apiPut("/settings/cold_storage/enabled", { value: String(enabled) });
      await apiPut("/settings/cold_storage/provider", { value: provider });
      await apiPut("/settings/cold_storage/bucket", { value: bucket });
      await apiPut("/settings/cold_storage/prefix", { value: prefix });
      await apiPut("/settings/cold_storage/after_days", { value: afterDays });
      if (provider === "s3") {
        await apiPut("/settings/cold_storage/aws_region", { value: region });
        await apiPut("/settings/cold_storage/aws_access_key", { value: accessKey });
        if (editSecret && secretKeyNew) {
          await apiPut("/settings/cold_storage/aws_secret_key", { value: secretKeyNew, is_secret: true });
        }
      }
      if (provider === "gcs" && editGcs && gcsCredsNew) {
        await apiPut("/settings/cold_storage/gcs_credentials", { value: gcsCredsNew, is_secret: true });
      }
      setSaveStatus("ok");
      reload();
      setTimeout(() => setSaveStatus("idle"), 3000);
    } catch {
      setSaveStatus("error");
    }
  }

  async function onTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const r = (await apiPost("/settings/cold-storage/test")) as { success: boolean; message: string };
      setTestResult(r);
    } catch (e) {
      setTestResult({ success: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Unavailable: {error}</div>;

  return (
    <div className="settings-section">
      <div className="settings-field">
        <label className="settings-label">Enable cold storage</label>
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      </div>
      <div className="settings-field">
        <label className="settings-label">Provider</label>
        <div className="settings-input-row">
          <button className={`settings-provider-btn${provider === "s3" ? " active" : ""}`} onClick={() => setProvider("s3")}>S3</button>
          <button className={`settings-provider-btn${provider === "gcs" ? " active" : ""}`} onClick={() => setProvider("gcs")}>GCS</button>
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label">Bucket</label>
        <input type="text" value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="my-audit-archive" className="settings-text-input" />
      </div>
      <div className="settings-field">
        <label className="settings-label">Prefix</label>
        <input type="text" value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="auditlens/" className="settings-text-input" />
      </div>
      <div className="settings-field">
        <label className="settings-label">Archive after</label>
        <div className="settings-input-row">
          <input type="number" min={1} max={3650} value={afterDays} onChange={(e) => setAfterDays(e.target.value)} className="settings-number-input" />
          <span className="muted">days</span>
        </div>
      </div>
      {provider === "s3" && (
        <>
          <div className="settings-field">
            <label className="settings-label">AWS Region</label>
            <input type="text" value={region} onChange={(e) => setRegion(e.target.value)} className="settings-text-input" />
          </div>
          <div className="settings-field">
            <label className="settings-label">Access Key ID</label>
            <input type="text" value={accessKey} onChange={(e) => setAccessKey(e.target.value)} className="settings-text-input" />
          </div>
          <div className="settings-field">
            <label className="settings-label">Secret Access Key</label>
            <div className="settings-input-row">
              {editSecret ? (
                <input type="password" value={secretKeyNew} onChange={(e) => setSecretKeyNew(e.target.value)} placeholder="Enter new secret key" className="settings-text-input" />
              ) : (
                <span className="settings-masked">••••••••</span>
              )}
              {!editSecret && <button className="settings-change-btn" onClick={() => setEditSecret(true)}>Change</button>}
              <span className="settings-isset">{secretIsSet ? "Currently set: Yes ✓" : "Currently set: No ✗"}</span>
            </div>
          </div>
        </>
      )}
      {provider === "gcs" && (
        <div className="settings-field">
          <label className="settings-label">GCS Credentials JSON</label>
          <div className="settings-input-row">
            {editGcs ? (
              <textarea value={gcsCredsNew} onChange={(e) => setGcsCredsNew(e.target.value)} placeholder='{"type":"service_account",...}' className="settings-textarea" />
            ) : (
              <span className="settings-masked">••••••••</span>
            )}
            {!editGcs && <button className="settings-change-btn" onClick={() => setEditGcs(true)}>Change</button>}
            <span className="settings-isset">{gcsIsSet ? "Currently set: Yes ✓" : "Currently set: No ✗"}</span>
          </div>
        </div>
      )}
      <div className="settings-actions">
        <button className="settings-save-btn" onClick={onSave} disabled={saveStatus === "saving"}>Save</button>
        <button className="settings-test-btn" onClick={onTest} disabled={testing}>{testing ? "Testing…" : "Test Connection"}</button>
        <SaveStatus status={saveStatus} />
      </div>
      {testResult && (
        <div className={`settings-test-result ${testResult.success ? "ok" : "error"}`}>
          {testResult.success ? "✓" : "✗"} {testResult.message}
        </div>
      )}
    </div>
  );
}

// ── Notifications Tab ─────────────────────────────────────────────────────────
function NotificationsTab() {
  return (
    <div className="settings-section">
      <p className="muted">
        Notification destinations are configured in <code>notifications.yml</code> at the repo root.
        Copy <code>notifications.example.yml</code> and restart the forwarder to pick up changes.
      </p>
      <p className="settings-info">
        Supported: Slack, Microsoft Teams, generic webhooks. Supports per-destination signal filters, min risk level, and dedup.
      </p>
    </div>
  );
}

// ── Actor Mappings Tab ────────────────────────────────────────────────────────
function ActorMappingsTab() {
  return (
    <div className="settings-section">
      <p className="muted">
        Actor display name overrides are configured in <code>actor_mappings.yml</code> at the repo root.
        Copy <code>actor_mappings.example.yml</code> and edit. Changes are hot-reloaded within 60 seconds.
      </p>
      <p className="settings-info">
        DB mappings (set via admin API) take priority over the YAML file overrides.
      </p>
    </div>
  );
}

// ── Data Export / Tableflow Tab ───────────────────────────────────────────────
type TableflowStatus = {
  enabled: boolean;
  topic: string;
  format: string | null;
  storage: string | null;
  cluster_cloud: string;
  eligible: boolean;
  ineligible_reason: string | null;
};

function TableflowTab() {
  const [status, setStatus] = useState<TableflowStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<"iceberg" | "delta">("iceberg");
  const [storageType, setStorageType] = useState<"managed" | "custom">("managed");
  const [storageBucket, setStorageBucket] = useState("");
  const [actionStatus, setActionStatus] = useState<"idle" | "working" | "ok" | "error">("idle");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [showCostNotice, setShowCostNotice] = useState(false);

  function loadStatus() {
    setLoading(true);
    setError(null);
    apiGet("/tableflow/status")
      .then((d) => setStatus(d as TableflowStatus))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadStatus(); }, []);

  async function onEnable() {
    setActionStatus("working");
    setActionMessage(null);
    try {
      await apiPost("/tableflow/enable", {
        format,
        storage_type: storageType,
        storage_bucket: storageType === "custom" ? storageBucket : null,
      });
      setActionStatus("ok");
      setShowCostNotice(true);
      loadStatus();
    } catch (e) {
      setActionStatus("error");
      setActionMessage(e instanceof Error ? e.message : String(e));
    }
  }

  async function onDisable() {
    setActionStatus("working");
    setActionMessage(null);
    try {
      await apiPost("/tableflow/disable");
      setActionStatus("ok");
      setShowCostNotice(false);
      loadStatus();
    } catch (e) {
      setActionStatus("error");
      setActionMessage(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">Apache Iceberg / Delta Lake export via Tableflow</h3>

      {loading ? (
        <div className="settings-skeleton">
          <div className="settings-skeleton-bar" style={{ width: "60%" }} />
          <div className="settings-skeleton-bar" style={{ width: "40%" }} />
        </div>
      ) : error ? (
        <div className="settings-access-denied">Unavailable: {error}</div>
      ) : status ? (
        <>
          <div style={{ marginBottom: 12 }}>
            {!status.eligible ? (
              <span className="tableflow-badge ineligible">NOT ELIGIBLE</span>
            ) : status.enabled ? (
              <span className="tableflow-badge enabled">ENABLED</span>
            ) : (
              <span className="tableflow-badge disabled">DISABLED</span>
            )}
          </div>

          {!status.eligible && (
            <p className="settings-info" style={{ color: "var(--critical)" }}>
              ⚠ Tableflow is not available for GCP clusters. Available on AWS and Azure only.
            </p>
          )}

          {status.eligible && !status.enabled && (
            <>
              <div className="settings-field">
                <label className="settings-label">Format</label>
                <div className="settings-input-row">
                  <button
                    className={`settings-provider-btn${format === "iceberg" ? " active" : ""}`}
                    onClick={() => setFormat("iceberg")}
                  >Iceberg</button>
                  <button
                    className={`settings-provider-btn${format === "delta" ? " active" : ""}`}
                    onClick={() => setFormat("delta")}
                  >Delta Lake</button>
                </div>
              </div>
              <div className="settings-field">
                <label className="settings-label">Storage</label>
                <div className="settings-input-row">
                  <button
                    className={`settings-provider-btn${storageType === "managed" ? " active" : ""}`}
                    onClick={() => setStorageType("managed")}
                    disabled={format === "delta"}
                  >Confluent managed</button>
                  <button
                    className={`settings-provider-btn${storageType === "custom" ? " active" : ""}`}
                    onClick={() => setStorageType("custom")}
                  >Bring your own</button>
                </div>
              </div>
              {storageType === "custom" && (
                <div className="settings-field">
                  <label className="settings-label">Bucket URI</label>
                  <input
                    type="text"
                    value={storageBucket}
                    onChange={(e) => setStorageBucket(e.target.value)}
                    placeholder={status.cluster_cloud === "azure"
                      ? "abfss://container@account.dfs.core.windows.net/prefix"
                      : "s3://bucket-name/prefix"}
                    className="settings-text-input"
                  />
                  <p className="settings-info" style={{ margin: "4px 0 0" }}>
                    {status.cluster_cloud === "azure"
                      ? "Azure: abfss://container@account.dfs.core.windows.net/prefix"
                      : "AWS: s3://bucket-name/prefix"}
                  </p>
                </div>
              )}
              <div className="settings-actions">
                <button
                  className="settings-save-btn"
                  onClick={onEnable}
                  disabled={actionStatus === "working" || (storageType === "custom" && !storageBucket)}
                >
                  {actionStatus === "working" ? "Enabling…" : "Enable Tableflow export →"}
                </button>
                {actionStatus === "error" && (
                  <span className="settings-save-status error">Error: {actionMessage}</span>
                )}
              </div>
            </>
          )}

          {status.eligible && status.enabled && (
            <>
              <p className="settings-info">
                ✅ Exporting <code>{status.topic}</code> as {status.format?.toUpperCase()} tables
              </p>
              <p className="settings-info muted">
                Query from: Snowflake, Athena, Databricks, Spark
              </p>
              <div className="settings-actions">
                <button
                  className="settings-test-btn"
                  onClick={onDisable}
                  disabled={actionStatus === "working"}
                >
                  {actionStatus === "working" ? "Disabling…" : "Disable"}
                </button>
                {actionStatus === "error" && (
                  <span className="settings-save-status error">Error: {actionMessage}</span>
                )}
              </div>
            </>
          )}

          {showCostNotice && (
            <p className="settings-info" style={{ marginTop: 12, background: "var(--panel)", padding: "8px 12px", borderRadius: 6 }}>
              ⓘ Tableflow costs ~$72/month (720 topic-hours × $0.10) plus $0.04/GB processed. Billed by Confluent directly.
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
const TABS = ["Retention", "Cold Storage", "Notifications", "Actor Mappings", "Data Export"] as const;
type Tab = (typeof TABS)[number];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Retention");
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    // Probe admin access
    fetch(`${API_BASE}/settings/retention`, { cache: "no-store" })
      .then((r) => { if (r.status === 401 || r.status === 403) setAccessDenied(true); })
      .catch(() => {});
  }, []);

  if (accessDenied) {
    return (
      <main className="page">
        <h1>Settings</h1>
        <div className="settings-access-denied">Access denied — admin token required.</div>
      </main>
    );
  }

  return (
    <main className="page">
      <h1>Settings</h1>
      <div className="settings-tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`settings-tab-btn${activeTab === tab ? " active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="settings-tab-content">
        {activeTab === "Retention" && <RetentionTab />}
        {activeTab === "Cold Storage" && <ColdStorageTab />}
        {activeTab === "Notifications" && <NotificationsTab />}
        {activeTab === "Actor Mappings" && <ActorMappingsTab />}
        {activeTab === "Data Export" && <TableflowTab />}
      </div>
    </main>
  );
}
