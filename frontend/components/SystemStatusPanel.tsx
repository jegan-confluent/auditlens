import type { SystemStatus } from "../lib/types";

const HIGH_LAG_THRESHOLD = 100_000;
const WRITE_STALE_MS = 60 * 60 * 1000;

function lagTone(lag: number | null | undefined): "" | "warning" {
  if (typeof lag !== "number") return "";
  return lag > HIGH_LAG_THRESHOLD ? "warning" : "";
}

function writeTone(iso: string | null | undefined): "" | "warning" {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  return Date.now() - ts > WRITE_STALE_MS ? "warning" : "";
}

export default function SystemStatusPanel({ status }: { status: SystemStatus }) {
  const eventCount = typeof status.db_health?.event_count === "number" ? status.db_health.event_count : "unknown";
  const lagClass = lagTone(status.consumer_lag);
  const writeClass = writeTone(status.db_last_successful_write);
  return (
    <div className="panel">
      <h2>System</h2>
      <div className="grid">
        <div><div className="muted">DB Mode</div><strong>{status.database_mode}</strong></div>
        <div><div className="muted">DB Events</div><strong>{eventCount}</strong></div>
        <div><div className="muted">Consumer</div><strong>{status.consumer_state}</strong></div>
        <div className={lagClass ? `system-cell ${lagClass}` : undefined}>
          <div className="muted">Lag</div>
          <strong>{status.consumer_lag ?? "unknown"}</strong>
          {lagClass === "warning" ? <span className="system-flag"> ⚠️ Forwarder behind</span> : null}
        </div>
        <div><div className="muted">Retries</div><strong>{status.retry_count}</strong></div>
        <div><div className="muted">DB Writer</div><strong>{status.db_writer_enabled ? status.db_writer_state : "disabled"}</strong></div>
        <div><div className="muted">DB Write Errors</div><strong>{status.db_write_error_total}</strong></div>
        <div className={writeClass ? `system-cell ${writeClass}` : undefined}>
          <div className="muted">Last DB Write</div>
          <strong>{status.db_last_successful_write || "never"}</strong>
          {writeClass === "warning" ? <span className="system-flag"> ⚠️ &gt;1h ago</span> : null}
        </div>
      </div>
      {status.last_error ? <p className="muted">Forwarder error: {status.last_error}</p> : null}
      {status.db_last_error ? <p className="muted">DB writer error: {status.db_last_error}</p> : null}
    </div>
  );
}
