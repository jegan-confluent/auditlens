"use client";

import { useEffect, useRef, useState } from "react";
import ErrorState from "../../components/ErrorState";
import LoadingState from "../../components/LoadingState";
import PipelineLagBanner from "../../components/PipelineLagBanner";
import { getForwarderHealth, getReadinessStatus, getSystemStatus, isAbortError, runForwarderVacuum } from "../../lib/api";
import type { ReadinessSnapshot } from "../../lib/api";
import type { ForwarderHealth, SystemStatus, VacuumResult } from "../../lib/types";

const HIGH_LAG_THRESHOLD = 100_000;
const LOW_LAG_THRESHOLD = 10_000;
const SLOW_PROCESSING_THRESHOLD = 10;
const FALLBACK_WARNING_THRESHOLD = 100;

type Tone = "ok" | "warning" | "critical" | "unknown";

function formatNumber(n: number | null | undefined): string {
  if (typeof n !== "number") return "—";
  return n.toLocaleString("en-US");
}

function formatBytes(n: number | null | undefined): string {
  if (typeof n !== "number" || n <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function lagTone(lag: number | null | undefined): Tone {
  if (typeof lag !== "number") return "unknown";
  if (lag > HIGH_LAG_THRESHOLD) return "critical";
  if (lag > LOW_LAG_THRESHOLD) return "warning";
  return "ok";
}

function storageTone(mode: string | undefined): Tone {
  if (mode === "critical" || mode === "emergency") return "critical";
  if (mode === "warning") return "warning";
  if (mode === "normal") return "ok";
  return "unknown";
}

function indicator(tone: Tone): string {
  if (tone === "critical") return "🔴";
  if (tone === "warning") return "🟡";
  if (tone === "ok") return "🟢";
  return "⚪";
}

function ScrollLink({ targetId, children }: { targetId: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      className="system-card-link"
      onClick={() => document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth" })}
    >
      {children}
    </button>
  );
}

export default function SystemPage() {
  const [health, setHealth] = useState<ForwarderHealth | null>(null);
  const [ready, setReady] = useState<ReadinessSnapshot | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vacuum, setVacuum] = useState<{ running: boolean; result: VacuumResult | null; error: string | null }>({
    running: false,
    result: null,
    error: null,
  });
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    Promise.all([
      getForwarderHealth(controller.signal),
      getReadinessStatus(controller.signal),
    ])
      .then(([h, r]) => {
        if (!mountedRef.current) return;
        setHealth(h);
        setReady(r);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        if (!mountedRef.current) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    getSystemStatus(controller.signal)
      .then((s) => {
        if (!mountedRef.current) return;
        setSystemStatus(s);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        // non-fatal — storage card shows "—"
      });
    return () => {
      mountedRef.current = false;
      controller.abort();
    };
  }, []);

  if (error) return <main className="page"><ErrorState message={error} /></main>;
  if (!health || !ready) return <main className="page"><LoadingState /></main>;

  const apiOk = ready.ok;
  const dbOk = apiOk;
  const consumerLag = typeof health.consumer_lag === "number" ? health.consumer_lag : null;
  const processingRate = typeof health.processing_rate === "number" ? health.processing_rate : 0;
  const consumerState = health.observability?.consumer_runtime?.consumer_state ?? "unknown";
  const lastPoll = health.observability?.consumer_runtime?.last_successful_poll ?? null;
  const recordsConsumed = health.observability?.consumer_runtime?.records_consumed_total ?? 0;
  const dbWriter = health.observability?.db_writer;
  const persistence = health.observability?.persistence_storage;
  const dataQuality = health.observability?.data_quality;
  const fwLagTone: Tone = lagTone(consumerLag);
  const fwHealthy = !health.error && consumerState === "connected" && processingRate > SLOW_PROCESSING_THRESHOLD && fwLagTone !== "critical";
  const fwTone: Tone = health.error ? "critical" : (consumerState !== "connected" ? "critical" : (fwLagTone === "critical" ? "critical" : (fwHealthy ? "ok" : "warning")));
  const stTone: Tone = storageTone(persistence?.storage_mode);
  const showStorageDetail = persistence?.storage_mode && persistence.storage_mode !== "normal";
  const dbFile = persistence?.db_file_bytes ?? 0;
  const dbMax = persistence?.db_max_bytes ?? persistence?.max_db_size ?? 0;
  const dbPct = dbMax > 0 ? Math.round((dbFile / dbMax) * 100) : 0;
  const reclaimable = persistence?.sqlite_reclaimable_bytes ?? 0;

  async function onVacuumClick() {
    setVacuum({ running: true, result: null, error: null });
    try {
      const result = await runForwarderVacuum();
      if (!mountedRef.current) return;
      setVacuum({ running: false, result, error: null });
      // Refresh health so the card updates after VACUUM.
      const refreshed = await getForwarderHealth();
      if (mountedRef.current) setHealth(refreshed);
    } catch (err) {
      if (!mountedRef.current) return;
      setVacuum({ running: false, result: null, error: err instanceof Error ? err.message : String(err) });
    }
  }

  return (
    <main className="page system-page">
      <h1 className="system-title">System</h1>

      <PipelineLagBanner />

      <section className="system-status-cards">
        <div className={`system-status-card ${apiOk ? "ok" : "critical"}`}>
          <div className="system-status-card-head">{indicator(apiOk ? "ok" : "critical")} API</div>
          <div className="system-status-card-headline">{apiOk ? "Ready" : "Down"}</div>
          <div className="system-status-card-detail">{formatNumber(recordsConsumed)} events</div>
        </div>
        <div className={`system-status-card ${dbOk ? "ok" : "critical"}`}>
          <div className="system-status-card-head">{indicator(dbOk ? "ok" : "critical")} Database</div>
          <div className="system-status-card-headline">Postgres</div>
          <div className="system-status-card-detail">
            Newest: {formatRelative(ready.newest_event)}<br />
            Oldest: {formatRelative(ready.oldest_event)}
          </div>
        </div>
        <ScrollLink targetId="forwarder-pipeline">
          <div className={`system-status-card ${fwTone}`}>
            <div className="system-status-card-head">{indicator(fwTone)} Forwarder</div>
            <div className="system-status-card-headline">{processingRate.toFixed(1)} msg/s</div>
            <div className="system-status-card-detail">
              {formatNumber(consumerLag)} lag<br />
              {consumerState}
            </div>
          </div>
        </ScrollLink>
        <ScrollLink targetId="storage-detail">
          <div className={`system-status-card ${stTone}`}>
            <div className="system-status-card-head">{indicator(stTone)} Storage</div>
            <div className="system-status-card-headline">{dbPct}% full</div>
            <div className="system-status-card-detail">
              {formatBytes(dbFile)} / {formatBytes(dbMax)}<br />
              {reclaimable > 0 ? `VACUUM reclaimable: ${formatBytes(reclaimable)}` : "No reclaim pending"}
            </div>
          </div>
        </ScrollLink>
        {systemStatus?.storage_health ? (
          <StorageHealthCard health={systemStatus.storage_health} />
        ) : null}
      </section>

      <section id="forwarder-pipeline" className="panel system-section">
        <h2>Forwarder pipeline</h2>
        <div className="system-pipeline">
          <PipelineRow tone="ok" stage="Kafka" metric="Source topic" detail="confluent-audit-log-events" />
          <PipelineRow
            tone={fwLagTone === "ok" ? "ok" : fwLagTone}
            stage="Consumer"
            metric={`${formatNumber(consumerLag)} lag`}
            detail={`${processingRate.toFixed(1)} msg/s · ${formatNumber(recordsConsumed)} processed · last poll ${formatRelative(lastPoll)}`}
          />
          <PipelineRow tone="ok" stage="Enrichment" metric="" detail={`Last ingest: ${formatRelative(health.freshness?.last_enriched_ingest_at)}`} />
          <PipelineRow
            tone={dbWriter?.db_writer_state === "connected" ? "ok" : "warning"}
            stage="DB Writer"
            metric={`${dbWriter?.db_write_error_total ?? 0} errors`}
            detail={`Batch: ${dbWriter?.db_write_batch_size ?? 0} · Last write: ${formatRelative(dbWriter?.db_last_successful_write)}`}
          />
          <PipelineRow
            tone="ok"
            stage="Postgres"
            metric={`${formatNumber(recordsConsumed)} events`}
            detail={`${dbWriter?.retention_days ?? 7} day retention`}
          />
          <SchemaRegistryRow health={health} />
        </div>
      </section>

      <section className="panel system-section">
        <h2>Data quality</h2>
        <ul className="system-quality">
          <QualityRow ok={(dataQuality?.missing_principal_total ?? 0) === 0} label="Missing principals" value={dataQuality?.missing_principal_total ?? 0} />
          <QualityRow ok={(dataQuality?.missing_resource_total ?? 0) === 0} label="Missing resources" value={dataQuality?.missing_resource_total ?? 0} />
          <QualityRow ok={(dataQuality?.unknown_method_total ?? 0) === 0} label="Parse errors" value={dataQuality?.unknown_method_total ?? 0} />
          <QualityRow
            ok={(dataQuality?.classification_fallback_total ?? 0) <= FALLBACK_WARNING_THRESHOLD}
            label="Classification fallbacks"
            value={dataQuality?.classification_fallback_total ?? 0}
          />
          <QualityRow ok info label="Suppressed auth noise" value={dataQuality?.suppressed_authz_noise_total ?? 0} />
        </ul>
      </section>

      {showStorageDetail ? (
        <section id="storage-detail" className="panel system-section">
          <h2>Storage detail</h2>
          <div className="system-storage">
            <div className="system-storage-headline">
              {indicator(stTone)} SQLite hot cache: {formatBytes(dbFile)} / {formatBytes(dbMax)} ({dbPct}%)
            </div>
            <div className="system-progress">
              <div className={`system-progress-fill ${stTone}`} style={{ width: `${Math.min(100, dbPct)}%` }} />
            </div>
            <div className="system-storage-meta">
              Reclaimable: {formatBytes(reclaimable)}
              {persistence?.last_vacuum_status === "success" && persistence.last_vacuum_at
                ? ` · Last VACUUM ${formatRelative(persistence.last_vacuum_at)}`
                : " · VACUUM not run"}
            </div>
            <div className="system-vacuum-actions">
              <button type="button" className="system-vacuum-button" disabled={vacuum.running} onClick={onVacuumClick}>
                {vacuum.running ? "Running…" : "Run VACUUM"}
              </button>
              {vacuum.result ? (
                <span className={vacuum.result.status === "success" ? "muted" : "system-vacuum-error"}>
                  {vacuum.result.status === "success"
                    ? `Reclaimed ${formatBytes(vacuum.result.reclaimed_bytes ?? 0)} in ${vacuum.result.duration_ms ?? 0} ms`
                    : `Failed: ${vacuum.result.error ?? "unknown error"}`}
                </span>
              ) : null}
              {vacuum.error ? <span className="system-vacuum-error">Failed: {vacuum.error}</span> : null}
            </div>
            <div className="system-retention">
              <div><strong>Retention policy</strong></div>
              <div>Hot cache: {persistence?.hot_cache_retention_hours ?? 24}h</div>
              <div>Postgres: {dbWriter?.retention_days ?? 7} days</div>
              {persistence?.data_loss_possible ? (
                <div className="system-retention-warning">⚠️ Data loss possible if storage stays critical (oldest rows trimmed first)</div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}

function StorageHealthCard({ health }: {
  health: NonNullable<SystemStatus["storage_health"]>;
}) {
  const tone: Tone = health.status === "critical" ? "critical" : health.status === "warning" ? "warning" : health.status === "healthy" ? "ok" : "unknown";
  return (
    <div className={`system-status-card ${tone}`}>
      <div className="system-status-card-head">{indicator(tone)} Postgres</div>
      <div className="system-status-card-headline">{health.db_size_pretty || "—"}</div>
      <div className="system-status-card-detail">
        {health.retention_days ? `${health.retention_days}d retention` : ""}<br />
        {health.status === "warning" ? "approaching limit" : health.status === "critical" ? "ACTION REQUIRED" : "healthy"}
      </div>
    </div>
  );
}

function PipelineRow({ tone, stage, metric, detail }: { tone: Tone; stage: string; metric: string; detail: string }) {
  return (
    <div className="system-pipeline-row">
      <span className="system-pipeline-tone">{indicator(tone)}</span>
      <span className="system-pipeline-stage">{stage}</span>
      <span className="system-pipeline-metric">{metric || "—"}</span>
      <span className="system-pipeline-detail muted">{detail}</span>
    </div>
  );
}

function QualityRow({ ok, info, label, value }: { ok: boolean; info?: boolean; label: string; value: number }) {
  const icon = info ? "ℹ️" : ok ? "✅" : "⚠️";
  return (
    <li className={`system-quality-row ${ok ? "ok" : "warning"}`}>
      <span className="system-quality-icon">{icon}</span>
      <span className="system-quality-label">{label}</span>
      <span className="system-quality-value">{value.toLocaleString("en-US")}</span>
    </li>
  );
}

function SchemaRegistryRow({ health }: { health: ForwarderHealth }) {
  const serialization = health.serialization;
  const mode = serialization?.enriched_topic ?? "unknown";
  const connected = !!serialization?.sr_connected;
  const url = serialization?.sr_url ?? null;

  let tone: Tone = "unknown";
  let metric = "—";
  let detail = "not configured";

  if (mode === "avro" && connected) {
    tone = "ok";
    metric = "avro ✅";
    detail = url ? `connected · ${url}` : "connected";
  } else if (url && mode === "json") {
    tone = "warning";
    metric = "json ⚠";
    detail = "SR set but producer is on JSON — register schemas or restart forwarder";
  } else if (url) {
    tone = "warning";
    metric = "json";
    detail = `${url} · ${connected ? "connected" : "disconnected"}`;
  } else {
    tone = "unknown";
    metric = "json";
    detail = "Schema Registry not configured (enriched topic publishes as JSON)";
  }

  return (
    <div className="system-pipeline-row">
      <span className="system-pipeline-tone">{indicator(tone)}</span>
      <span className="system-pipeline-stage">Schema Registry</span>
      <span className="system-pipeline-metric">{metric}</span>
      <span className="system-pipeline-detail muted">{detail}</span>
    </div>
  );
}
