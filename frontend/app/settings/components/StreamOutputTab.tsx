"use client";

import { useEffect, useState } from "react";
import { getForwarderHealth } from "../../../lib/api";
import type { ForwarderHealth } from "../../../lib/types";
import { apiGet } from "./shared";

type StreamOutputInfo = {
  topics: {
    raw: string;
    normalized: string;
    enriched: string;
    denials: string;
    highrisk: string;
    alerts: string;
    dlq: string;
  };
  enriched_subject: string;
  schema_registry: {
    configured: boolean;
    url: string | null;
    enriched_avro_ready: boolean;
    error: string | null;
  };
  confluent: {
    env_id: string | null;
    cluster_id: string | null;
    flink_workspace_url: string | null;
  };
};

type Props = {
  onGotoSchemaRegistry: () => void;
  onGotoTableflow: () => void;
};

const TOPIC_ROWS: Array<{ key: keyof StreamOutputInfo["topics"]; description: string }> = [
  { key: "enriched",   description: "Fully enriched + classified events (Avro when SR configured)" },
  { key: "denials",    description: "Denied events only" },
  { key: "highrisk",   description: "High-risk events only" },
  { key: "alerts",     description: "Action-required alerts" },
  { key: "raw",        description: "Replay envelope (original events)" },
  { key: "normalized", description: "Flattened events, no enrichment" },
  { key: "dlq",        description: "Failed events with error metadata" },
];

export function StreamOutputTab({ onGotoSchemaRegistry, onGotoTableflow }: Props) {
  const [info, setInfo] = useState<StreamOutputInfo | null>(null);
  const [health, setHealth] = useState<ForwarderHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  useEffect(() => {
    let aborted = false;
    setLoading(true);
    // Fetch both in parallel — the format badge needs the forwarder's live
    // serialization state, not just SR registration.
    Promise.all([
      apiGet("/settings/stream_output/info").catch((e: Error) => { throw e; }),
      getForwarderHealth().catch(() => null as ForwarderHealth | null),
    ])
      .then(([infoData, healthData]) => {
        if (aborted) return;
        setInfo(infoData as StreamOutputInfo);
        if (healthData) setHealth(healthData);
      })
      .catch((e: Error) => { if (!aborted) setError(e.message); })
      .finally(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; };
  }, []);

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text).then(
      () => {
        setCopiedKey(key);
        setTimeout(() => setCopiedKey(null), 1200);
      },
      () => { /* clipboard blocked — fail silent */ }
    );
  }

  if (loading) return <div className="muted">Loading…</div>;
  if (error) return <div className="settings-access-denied">Unavailable: {error}</div>;
  if (!info) return null;

  const srConfigured = info.schema_registry.configured;
  const schemasRegistered = info.schema_registry.enriched_avro_ready;
  const flinkUrl = info.confluent.flink_workspace_url;
  const allPrereqsReady = srConfigured && schemasRegistered;
  const enrichedTopic = info.topics.enriched;
  const srUrl = info.schema_registry.url ?? "https://YOUR_SR_URL";
  // Live producer state — added 2026-05-27 so the format badge reflects
  // what the forwarder is ACTUALLY emitting, not just what SR has
  // registered. If the forwarder failed Avro init at startup, SR can be
  // configured + schemas registered but the producer is still on JSON.
  const liveSerializationMode = health?.serialization?.enriched_topic ?? "unknown";

  // Confluent Cloud Flink SQL workspace example — topics with SR-bound
  // schemas are auto-discoverable as catalog tables. The SELECT shape
  // matches the AuditLens enriched event vocabulary.
  const flinkSampleQuery =
`-- 1-hour rolling denial rate per actor
SELECT actor_display_name, environment_name,
       COUNT(*) as denial_count,
       TUMBLE_END(event_time, INTERVAL '1' HOUR) as window_end
FROM audit_enriched
WHERE is_denied = true
GROUP BY actor_display_name, environment_name,
         TUMBLE(event_time, INTERVAL '1' HOUR)
HAVING COUNT(*) >= 5;`;

  // Apache Flink (non-Confluent) DDL template, pre-filled with the
  // configured SR URL + topic name. Customer fills in their own
  // bootstrap + SASL secret and the AuditLens Avro schema is bound via
  // Schema Registry.
  const flinkSampleDdl =
`-- For Apache Flink + kafka-connector deployments. In Confluent Cloud's
-- Flink SQL Workspace the topic is auto-bound — paste the SELECT below
-- directly, no DDL needed.
CREATE TABLE audit_enriched (
  event_fingerprint  STRING,
  \`timestamp\`        STRING,
  actor              STRING,
  action             STRING,
  resource_name      STRING,
  signal_type        STRING,
  signal_reason      STRING,
  risk_level         STRING,
  is_denied          BOOLEAN,
  is_failure         BOOLEAN,
  source_ip          STRING,
  environment_id     STRING,
  cluster_id         STRING,
  event_time         AS TO_TIMESTAMP_LTZ(CAST(\`timestamp\` AS BIGINT), 3),
  WATERMARK FOR event_time AS event_time - INTERVAL '5' SECOND
) WITH (
  'connector'                          = 'kafka',
  'topic'                              = '${enrichedTopic}',
  'properties.bootstrap.servers'       = 'YOUR_BOOTSTRAP',
  'properties.security.protocol'       = 'SASL_SSL',
  'properties.sasl.mechanism'          = 'PLAIN',
  'properties.sasl.jaas.config'        = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="YOUR_KEY" password="YOUR_SECRET";',
  'value.format'                       = 'avro-confluent',
  'value.avro-confluent.url'           = '${srUrl}',
  'value.avro-confluent.basic-auth.credentials-source' = 'USER_INFO',
  'value.avro-confluent.basic-auth.user-info'          = 'YOUR_SR_KEY:YOUR_SR_SECRET',
  'scan.startup.mode'                  = 'latest-offset'
);`;

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">Stream Output</h3>
      <p className="settings-info">
        Output topics, Avro readiness, and Flink quick-start. Read-only —
        configure SR + Tableflow in their own tabs.
      </p>

      {/* ── Section A — Output Topics ────────────────────────────────── */}
      <div style={{ marginTop: 18 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>
          AuditLens publishes to these Kafka topics
        </div>
        <table style={{ borderCollapse: "collapse", width: "100%", maxWidth: 760, fontSize: "0.9em" }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              <th style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)" }}>Topic</th>
              <th style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)" }}>Description</th>
              <th style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)", width: 110 }}>Format</th>
              <th style={{ padding: "6px 8px", borderBottom: "1px solid var(--border)", width: 80 }} aria-label="copy" />
            </tr>
          </thead>
          <tbody>
            {TOPIC_ROWS.map(({ key, description }) => {
              const topic = info.topics[key];
              const isEnriched = key === "enriched";
              let formatLabel = "JSON";
              let formatStyle: React.CSSProperties = { color: "var(--muted)" };
              if (isEnriched) {
                if (liveSerializationMode === "avro") {
                  formatLabel = "Avro ✅";
                  formatStyle = { color: "var(--success)" };
                } else if (srConfigured && schemasRegistered) {
                  // SR is set up but forwarder is still on JSON — typically
                  // means the forwarder restarted before schemas were
                  // registered, or AvroSerializer construction failed.
                  formatLabel = "JSON ⚠ forwarder using JSON (restart required?)";
                  formatStyle = { color: "var(--warning)" };
                } else if (srConfigured) {
                  formatLabel = "JSON (register schemas)";
                  formatStyle = { color: "var(--warning)" };
                } else {
                  formatLabel = "JSON (no SR)";
                  formatStyle = { color: "var(--muted)" };
                }
              }
              return (
                <tr key={key}>
                  <td style={{ padding: "6px 8px", fontFamily: "var(--font-mono)" }}>{topic}</td>
                  <td style={{ padding: "6px 8px", color: "var(--muted)" }}>{description}</td>
                  <td style={{ padding: "6px 8px", fontSize: "0.85em", ...formatStyle }}>{formatLabel}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right" }}>
                    <button
                      className="settings-test-btn"
                      style={{ padding: "2px 8px", fontSize: "0.85em" }}
                      onClick={() => copy(topic, key)}
                    >
                      {copiedKey === key ? "Copied" : "Copy"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ── Section B — Flink SQL Quickstart ─────────────────────────── */}
      <div style={{ marginTop: 24 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Flink SQL Quickstart</div>

        <div style={{ marginBottom: 12 }}>
          <PrereqRow
            ok={srConfigured}
            label="Schema Registry configured"
            action={!srConfigured ? { label: "Configure →", onClick: onGotoSchemaRegistry } : undefined}
          />
          <PrereqRow
            ok={schemasRegistered}
            label="Schemas registered"
            action={!schemasRegistered ? { label: "Register →", onClick: onGotoSchemaRegistry } : undefined}
            hint={!srConfigured ? "Requires Schema Registry first" : undefined}
          />
          <PrereqRow
            ok={!!flinkUrl}
            label="Flink compute pool created"
            hint={
              flinkUrl
                ? "Open Confluent Cloud to confirm a pool exists in this env."
                : "Set CONFLUENT_ENV_ID in .env to enable the deep-link."
            }
            action={flinkUrl ? { label: "Open Confluent Cloud ↗", href: flinkUrl } : undefined}
          />
          {allPrereqsReady && flinkUrl && (
            <div style={{ marginTop: 8, color: "var(--success)", fontWeight: 600 }}>
              ✅ Ready for Flink
            </div>
          )}
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontWeight: 600 }}>Sample DDL (Apache Flink + Kafka)</span>
            <button
              className="settings-test-btn"
              style={{ padding: "2px 8px", fontSize: "0.85em" }}
              onClick={() => copy(flinkSampleDdl, "ddl")}
            >
              {copiedKey === "ddl" ? "Copied" : "Copy DDL"}
            </button>
          </div>
          <pre
            style={{
              background: "var(--panel)",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: "0.8em",
              overflowX: "auto",
              maxWidth: 760,
              margin: 0,
            }}
          >
            <code>{flinkSampleDdl}</code>
          </pre>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontWeight: 600 }}>Sample query (denial rate per actor)</span>
            <button
              className="settings-test-btn"
              style={{ padding: "2px 8px", fontSize: "0.85em" }}
              onClick={() => copy(flinkSampleQuery, "query")}
            >
              {copiedKey === "query" ? "Copied" : "Copy query"}
            </button>
          </div>
          <pre
            style={{
              background: "var(--panel)",
              padding: "8px 12px",
              borderRadius: 6,
              fontSize: "0.8em",
              overflowX: "auto",
              maxWidth: 760,
              margin: 0,
            }}
          >
            <code>{flinkSampleQuery}</code>
          </pre>
        </div>

        {flinkUrl && (
          <a
            href={flinkUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--accent)" }}
          >
            Open Flink in Confluent Cloud →
          </a>
        )}
      </div>

      {/* ── Section C — Tableflow / Iceberg pointer ──────────────────── */}
      <div style={{ marginTop: 24, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Tableflow / Iceberg</div>
        <p className="settings-info">
          To query enriched events as an Iceberg or Delta Lake table from
          Snowflake / Athena / Databricks / Spark, configure Tableflow in
          the Tableflow tab →
        </p>
        <button className="settings-save-btn" onClick={onGotoTableflow}>
          Go to Tableflow →
        </button>
      </div>
    </div>
  );
}

type PrereqRowProps = {
  ok: boolean;
  label: string;
  hint?: string;
  action?: { label: string; onClick?: () => void; href?: string };
};

function PrereqRow({ ok, label, hint, action }: PrereqRowProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "4px 0",
        fontFamily: "var(--font-mono)",
        fontSize: 13,
      }}
    >
      <span aria-hidden style={{ width: 16 }}>{ok ? "✅" : "☐"}</span>
      <span style={{ color: ok ? "var(--success)" : "var(--muted)", minWidth: 220 }}>{label}</span>
      {hint && <span style={{ color: "var(--muted)", fontSize: "0.9em" }}>{hint}</span>}
      {action && action.href && (
        <a href={action.href} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
          {action.label}
        </a>
      )}
      {action && action.onClick && (
        <button
          className="settings-test-btn"
          style={{ padding: "2px 8px", fontSize: "0.85em" }}
          onClick={action.onClick}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
