import type { SystemStatus } from "../lib/types";

export default function SystemStatusPanel({ status }: { status: SystemStatus }) {
  const eventCount = typeof status.db_health?.event_count === "number" ? status.db_health.event_count : "unknown";
  return (
    <div className="panel">
      <h2>System</h2>
      <div className="grid">
        <div><div className="muted">DB Mode</div><strong>{status.database_mode}</strong></div>
        <div><div className="muted">DB Events</div><strong>{eventCount}</strong></div>
        <div><div className="muted">Consumer</div><strong>{status.consumer_state}</strong></div>
        <div><div className="muted">Lag</div><strong>{status.consumer_lag ?? "unknown"}</strong></div>
        <div><div className="muted">Retries</div><strong>{status.retry_count}</strong></div>
        <div><div className="muted">DB Writer</div><strong>{status.db_writer_enabled ? status.db_writer_state : "disabled"}</strong></div>
        <div><div className="muted">DB Write Errors</div><strong>{status.db_write_error_total}</strong></div>
        <div><div className="muted">Last DB Write</div><strong>{status.db_last_successful_write || "never"}</strong></div>
      </div>
      {status.last_error ? <p className="muted">Forwarder error: {status.last_error}</p> : null}
      {status.db_last_error ? <p className="muted">DB writer error: {status.db_last_error}</p> : null}
    </div>
  );
}
