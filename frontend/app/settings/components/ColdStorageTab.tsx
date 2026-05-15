"use client";

import { useEffect, useState } from "react";
import { apiPost, apiPut, SaveStatus, useSetting } from "./shared";

export function ColdStorageTab() {
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
