"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "./shared";

type TableflowStatus = {
  enabled: boolean;
  topic: string;
  format: string | null;
  storage: string | null;
  cluster_cloud: string;
  eligible: boolean;
  ineligible_reason: string | null;
};

export function TableflowTab() {
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
