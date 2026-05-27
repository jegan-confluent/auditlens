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

type PrereqItem = {
  ok: boolean;
  value: string;
  message: string;
};

type Prerequisites = {
  creds_missing: boolean;
  all_passed: boolean;
  api_error?: string;
  message?: string;
  prerequisites: {
    cluster_type?: PrereqItem;
    cloud_provider?: PrereqItem;
    schema_registry?: PrereqItem;
    region?: PrereqItem;
  };
  docs_url: string;
};

const PREREQ_LABELS: Record<keyof Prerequisites["prerequisites"], string> = {
  cluster_type:    "Cluster type",
  cloud_provider:  "Cloud provider",
  schema_registry: "Schema Registry",
  region:          "Region",
};
const PREREQ_ORDER: (keyof Prerequisites["prerequisites"])[] = [
  "cluster_type",
  "cloud_provider",
  "schema_registry",
  "region",
];

type SchemaRegistrationResult = {
  status?: "ok" | "skipped" | "error";
  reason?: string;
  subject?: string;
  schema_id?: number | null;
};

export function TableflowTab() {
  const [prereqs, setPrereqs] = useState<Prerequisites | null>(null);
  const [status, setStatus] = useState<TableflowStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<"iceberg" | "delta">("iceberg");
  const [storageType, setStorageType] = useState<"managed" | "custom">("managed");
  const [storageBucket, setStorageBucket] = useState("");
  const [actionStatus, setActionStatus] = useState<"idle" | "working" | "ok" | "error">("idle");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [showCostNotice, setShowCostNotice] = useState(false);
  const [schemaReg, setSchemaReg] = useState<SchemaRegistrationResult | null>(null);

  function loadAll() {
    setLoading(true);
    setError(null);
    // Always fetch prerequisites first — it's a cheap CC /cmk read that
    // never touches the Tableflow API, so it works even when Tableflow
    // itself would 404. /tableflow/status is only worth calling when prereqs
    // either pass or are unknown (creds missing); on a hard fail we skip it
    // entirely to avoid the misleading "Error: 404 Not Found" the user used
    // to see.
    apiGet("/tableflow/prerequisites")
      .then((p) => {
        const prereqResult = p as Prerequisites;
        setPrereqs(prereqResult);
        const shouldFetchStatus =
          prereqResult.creds_missing || prereqResult.all_passed;
        if (!shouldFetchStatus) {
          return null;
        }
        return apiGet("/tableflow/status").catch(() => null);
      })
      .then((s) => {
        if (s) setStatus(s as TableflowStatus);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadAll(); }, []);

  async function onEnable() {
    setActionStatus("working");
    setActionMessage(null);
    setSchemaReg(null);
    try {
      const response = (await apiPost("/tableflow/enable", {
        format,
        storage_type: storageType,
        storage_bucket: storageType === "custom" ? storageBucket : null,
      })) as { enabled?: boolean; schema_registration?: SchemaRegistrationResult };
      setActionStatus("ok");
      setShowCostNotice(true);
      if (response?.schema_registration) {
        setSchemaReg(response.schema_registration);
      }
      loadAll();
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
      loadAll();
    } catch (e) {
      setActionStatus("error");
      setActionMessage(e instanceof Error ? e.message : String(e));
    }
  }

  const formAllowed =
    !!prereqs && (prereqs.creds_missing || prereqs.all_passed) && !!status;

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">Apache Iceberg / Delta Lake export via Tableflow</h3>
      <p className="settings-info" style={{ marginTop: -4, marginBottom: 12 }}>
        Export audit.enriched.v1 as an Iceberg or Delta Lake table queryable
        from Snowflake, Athena, Databricks, or Spark.
      </p>

      {loading ? (
        <div className="settings-skeleton">
          <div className="settings-skeleton-bar" style={{ width: "60%" }} />
          <div className="settings-skeleton-bar" style={{ width: "40%" }} />
        </div>
      ) : error ? (
        <div className="settings-access-denied">Unavailable: {error}</div>
      ) : prereqs ? (
        <>
          <PrerequisitesPanel prereqs={prereqs} />

          {/* Form gating: hide when prereqs fail. Show with a warning banner
              when creds are missing (we can't verify, so let the operator try).
              Show normally when prereqs pass. */}
          {formAllowed && status ? (
            <TableflowForm
              status={status}
              format={format}
              setFormat={setFormat}
              storageType={storageType}
              setStorageType={setStorageType}
              storageBucket={storageBucket}
              setStorageBucket={setStorageBucket}
              actionStatus={actionStatus}
              actionMessage={actionMessage}
              showCostNotice={showCostNotice}
              schemaReg={schemaReg}
              onEnable={onEnable}
              onDisable={onDisable}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function PrerequisitesPanel({ prereqs }: { prereqs: Prerequisites }) {
  if (prereqs.creds_missing) {
    return (
      <div
        className="settings-info"
        style={{ background: "var(--panel)", padding: "8px 12px", borderRadius: 6, marginBottom: 12 }}
      >
        ℹ️ Add your Confluent Cloud API key (plus <code>CONFLUENT_CLUSTER_ID</code> /
        <code> CONFLUENT_ENV_ID</code>) in Settings to enable automatic prerequisite
        checking. Showing the form below without verification — Tableflow may still
        reject the request.
      </div>
    );
  }

  if (prereqs.api_error) {
    return (
      <div
        className="settings-info"
        style={{ background: "var(--panel)", padding: "8px 12px", borderRadius: 6, marginBottom: 12, color: "var(--warning)" }}
      >
        ⚠️ Could not reach Confluent Cloud to verify prerequisites: <code>{prereqs.api_error}</code>.
        Check the Cloud API key and try again. <DocsLink url={prereqs.docs_url} />
      </div>
    );
  }

  const rows = PREREQ_ORDER.map((k) => {
    const item = prereqs.prerequisites[k];
    if (!item) return null;
    const icon = item.ok ? "✅" : "❌";
    return (
      <div key={k} style={{ display: "flex", gap: 8, fontFamily: "var(--font-mono)", fontSize: 13, marginBottom: 4 }}>
        <span aria-hidden>{icon}</span>
        <span style={{ minWidth: 130, color: "var(--muted)" }}>{PREREQ_LABELS[k]}:</span>
        <span style={{ color: item.ok ? "var(--success)" : "var(--critical)" }}>
          {item.message}
        </span>
      </div>
    );
  });

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>Tableflow prerequisites</div>
      <div>{rows}</div>
      {!prereqs.all_passed && (
        <p className="settings-info" style={{ marginTop: 8, color: "var(--critical)" }}>
          One or more prerequisites are not satisfied. Resolve them on the
          Confluent side before enabling Tableflow. <DocsLink url={prereqs.docs_url} />
        </p>
      )}
    </div>
  );
}

function DocsLink({ url }: { url: string }) {
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
      See Confluent docs ↗
    </a>
  );
}

type FormProps = {
  status: TableflowStatus;
  format: "iceberg" | "delta";
  setFormat: (v: "iceberg" | "delta") => void;
  storageType: "managed" | "custom";
  setStorageType: (v: "managed" | "custom") => void;
  storageBucket: string;
  setStorageBucket: (v: string) => void;
  actionStatus: "idle" | "working" | "ok" | "error";
  actionMessage: string | null;
  showCostNotice: boolean;
  schemaReg: SchemaRegistrationResult | null;
  onEnable: () => void;
  onDisable: () => void;
};

function TableflowForm(p: FormProps) {
  const { status } = p;
  return (
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
                className={`settings-provider-btn${p.format === "iceberg" ? " active" : ""}`}
                onClick={() => p.setFormat("iceberg")}
              >Iceberg</button>
              <button
                className={`settings-provider-btn${p.format === "delta" ? " active" : ""}`}
                onClick={() => p.setFormat("delta")}
              >Delta Lake</button>
            </div>
          </div>
          <div className="settings-field">
            <label className="settings-label">Storage</label>
            <div className="settings-input-row">
              <button
                className={`settings-provider-btn${p.storageType === "managed" ? " active" : ""}`}
                onClick={() => p.setStorageType("managed")}
                disabled={p.format === "delta"}
              >Confluent managed</button>
              <button
                className={`settings-provider-btn${p.storageType === "custom" ? " active" : ""}`}
                onClick={() => p.setStorageType("custom")}
              >Bring your own</button>
            </div>
          </div>
          {p.storageType === "custom" && (
            <div className="settings-field">
              <label className="settings-label">Bucket URI</label>
              <input
                type="text"
                value={p.storageBucket}
                onChange={(e) => p.setStorageBucket(e.target.value)}
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
              onClick={p.onEnable}
              disabled={p.actionStatus === "working" || (p.storageType === "custom" && !p.storageBucket)}
            >
              {p.actionStatus === "working" ? "Enabling…" : "Enable Tableflow export →"}
            </button>
            {p.actionStatus === "error" && (
              <span className="settings-save-status error">Error: {p.actionMessage}</span>
            )}
          </div>
        </>
      )}

      {status.eligible && status.enabled && (
        <>
          <p className="settings-info">
            ✅ Exporting <code>{status.topic}</code> as {status.format?.toUpperCase()} tables
          </p>
          {p.schemaReg && (
            <p className="settings-info" style={{ marginTop: -4 }}>
              {p.schemaReg.status === "ok" && (
                <>✅ Schema registered (<code>{p.schemaReg.subject ?? "audit.enriched.v1-value"}</code>
                {p.schemaReg.schema_id != null && <>, id={p.schemaReg.schema_id}</>})</>
              )}
              {p.schemaReg.status === "skipped" && (
                <span style={{ color: "var(--muted)" }}>
                  ⏭ Schema already registered (skipped){p.schemaReg.reason ? ` — ${p.schemaReg.reason}` : ""}
                </span>
              )}
              {p.schemaReg.status === "error" && (
                <span style={{ color: "var(--warning)" }}>
                  ⚠ Schema registration failed: {p.schemaReg.reason ?? "unknown error"} — run Register schemas in the Schema Registry tab.
                </span>
              )}
            </p>
          )}
          <p className="settings-info muted">
            Query from: Snowflake, Athena, Databricks, Spark
          </p>
          <div className="settings-actions">
            <button
              className="settings-test-btn"
              onClick={p.onDisable}
              disabled={p.actionStatus === "working"}
            >
              {p.actionStatus === "working" ? "Disabling…" : "Disable"}
            </button>
            {p.actionStatus === "error" && (
              <span className="settings-save-status error">Error: {p.actionMessage}</span>
            )}
          </div>
        </>
      )}

      {p.showCostNotice && (
        <p className="settings-info" style={{ marginTop: 12, background: "var(--panel)", padding: "8px 12px", borderRadius: 6 }}>
          ⓘ Tableflow costs ~$72/month (720 topic-hours × $0.10) plus $0.04/GB processed. Billed by Confluent directly.
        </p>
      )}
    </>
  );
}
