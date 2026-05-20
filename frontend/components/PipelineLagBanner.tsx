"use client";

import { useEffect, useState } from "react";
import { useSystemStatus } from "../lib/hooks/useSystemStatus";
import type { PipelineLag, PipelineStatus } from "../lib/types";

// Phase 2 Fix 3: surface DB-vs-Kafka pipeline health at the top of the
// System page. Detect / surface / inform — no auto-replay button. The
// command shown is informational only and uses --hours N (computed from
// db_behind_seconds) since the existing CLI does not support a
// --from-timestamp flag.
//
// Polling: shared 30-s heartbeat via useSystemStatus() so this banner
// no longer spawns its own setInterval. The hook collapses every
// /system/status subscriber on the page (events page included) into
// one request per 30 s.
// Severity ordering so a worsening status reappears even after dismiss.
const STATUS_RANK: Record<PipelineStatus, number> = {
  healthy: 0,
  unknown: 1,
  degraded: 2,
  stalled: 3,
};
const SESSION_KEY = "auditlens.pipeline_banner_dismissed_rank";

function formatMinutesAgo(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function formatBehind(seconds: number | null | undefined): string {
  if (typeof seconds !== "number") return "unknown";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

function formatNumber(n: number | null | undefined): string {
  if (typeof n !== "number") return "unknown";
  return n.toLocaleString();
}

/**
 * Replay window in hours, derived from how far behind the DB is. The CLI
 * supports `--hours N` (existing flag) — we round up so the replay
 * always covers at least the lagging window, with a 1-hour floor.
 */
function replayHours(behindSeconds: number | null | undefined): number {
  if (typeof behindSeconds !== "number" || behindSeconds <= 0) return 1;
  return Math.max(1, Math.ceil(behindSeconds / 3600));
}

function readDismissedRank(): number {
  if (typeof window === "undefined") return -1;
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return -1;
    const parsed = parseInt(raw, 10);
    return Number.isFinite(parsed) ? parsed : -1;
  } catch {
    return -1;
  }
}

function writeDismissedRank(rank: number): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(SESSION_KEY, String(rank));
  } catch {
    // sessionStorage may be unavailable (private mode, etc.) — non-fatal.
  }
}

export default function PipelineLagBanner() {
  const { status } = useSystemStatus();
  const [dismissedRank, setDismissedRank] = useState<number>(-1);

  useEffect(() => {
    setDismissedRank(readDismissedRank());
  }, []);

  if (!status) return null;
  const ps: PipelineStatus = status.pipeline_status ?? "unknown";
  if (ps === "healthy") return null;

  // Hide if the user already dismissed this severity or higher. If
  // status escalates above the dismissed rank, banner reappears.
  if (dismissedRank >= STATUS_RANK[ps]) return null;

  const lag: PipelineLag | undefined = status.pipeline_lag ?? undefined;
  const lagMessages = lag?.kafka_consumer_lag_messages;
  const lastWrite = lag?.forwarder_last_write_at;
  const dbLatest = lag?.db_latest_event_at;
  const dbBehindSeconds = lag?.db_behind_seconds;
  const replayRecommended = lag?.replay_recommended ?? false;

  const heading =
    ps === "stalled"
      ? "🔴 Pipeline stalled — DB may be missing events"
      : ps === "degraded"
      ? `⚠️ Pipeline degraded — DB is ${formatBehind(dbBehindSeconds)} behind Kafka`
      : "⚪ Pipeline status unknown — forwarder unreachable";

  function onDismiss() {
    const rank = STATUS_RANK[ps];
    writeDismissedRank(rank);
    setDismissedRank(rank);
  }

  return (
    <section className={`pipeline-banner pipeline-banner-${ps}`} aria-live="polite">
      <header className="pipeline-banner-head">
        <strong>{heading}</strong>
        <button type="button" className="pipeline-banner-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </header>
      {ps !== "unknown" ? (
        <ul className="pipeline-banner-detail">
          <li>Consumer lag: {formatNumber(lagMessages)} messages</li>
          <li>Last DB write: {formatMinutesAgo(lastWrite)}</li>
          {ps === "stalled" ? (
            <>
              <li>DB latest event: {dbLatest ? formatMinutesAgo(dbLatest) : "unknown"}</li>
              <li>Replay recommended: {replayRecommended ? "Yes" : "No"}</li>
            </>
          ) : null}
        </ul>
      ) : null}
      {ps === "stalled" ? (
        <details className="pipeline-banner-replay">
          <summary>View replay instructions</summary>
          <p className="muted">
            Run from the host where docker compose is configured. Replays the
            last <strong>{replayHours(dbBehindSeconds)} hour(s)</strong> from
            audit.raw.v1 to rebuild any tail missing from Postgres. Does not
            modify Kafka topics.
          </p>
          <pre className="pipeline-banner-cmd">
{`docker compose exec auditlens-forwarder \\
  python audit_forwarder.py replay --hours ${replayHours(dbBehindSeconds)}`}
          </pre>
        </details>
      ) : null}
    </section>
  );
}
