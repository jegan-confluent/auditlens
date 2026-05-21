"""Lightweight durable persistence for AuditLens product APIs."""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

import orjson

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Hard ceiling on SQLite page count for new connections — 8 GiB at 4 KiB
# pages. The application-level db_max_bytes is much smaller (1 GiB by
# default) but we lift the per-connection ceiling so a future VACUUM /
# rotation has headroom to rebuild the file. Default SQLite
# max_page_count is effectively unlimited, but some packaged builds have
# trimmed it; setting it explicitly is cheap insurance.
_SQLITE_MAX_PAGE_COUNT = 2_097_152

# 50 MB threshold for triggering a startup incremental vacuum. Below
# this the rebuild cost is not worth the disk reclaim.
_SQLITE_STARTUP_RECLAIM_THRESHOLD_BYTES = 50 * 1024 * 1024


def _apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Settings every SQLite connection in the product store should have.

    auto_vacuum = INCREMENTAL only takes effect when set BEFORE any
    table is created on a fresh database. On a database that was created
    with auto_vacuum = NONE this is a silent no-op until a full VACUUM
    rewrites the file with the new setting. On rotation we always create
    the new file fresh, so the new file ends up with auto_vacuum = INCREMENTAL.

    temp_store = MEMORY avoids using the container's /tmp tmpfs (capped
    at ~100 MB) for SQLite scratch, which is what makes a full VACUUM
    fail with "database or disk is full" on a multi-hundred-MB hot cache.
    """
    try:
        conn.execute(f"PRAGMA max_page_count = {_SQLITE_MAX_PAGE_COUNT}")
    except Exception as exc:
        logger.debug("max_page_count pragma failed: %s", exc)
    try:
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    except Exception as exc:
        logger.debug("auto_vacuum pragma failed: %s", exc)
    try:
        conn.execute("PRAGMA temp_store = MEMORY")
    except Exception as exc:
        logger.debug("temp_store pragma failed: %s", exc)


def heal_sqlite_on_startup(db_path: str) -> Dict[str, Any]:
    """Best-effort SQLite repair before the store opens its long-lived connection.

    Runs an ``incremental_vacuum`` if a meaningful amount of the file is
    freelist pages. If that doesn't make progress (most often because the
    legacy file was created with ``auto_vacuum = NONE``) the file is
    deleted so the next ``initialize()`` recreates it with the correct
    pragmas. Postgres is the durable source of truth — losing the SQLite
    hot cache is recoverable via Kafka replay.
    """
    result: Dict[str, Any] = {"action": "noop", "path": db_path}
    if not db_path or not os.path.exists(db_path):
        result["action"] = "absent"
        return result
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(f"PRAGMA max_page_count = {_SQLITE_MAX_PAGE_COUNT}")
            conn.execute("PRAGMA temp_store = MEMORY")
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0] or 4096)
            freelist_before = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            reclaimable_bytes = page_size * freelist_before
            reclaimable_mb = reclaimable_bytes / 1024 / 1024
            logger.info(
                "SQLite startup: reclaimable=%dMB freelist=%d page_size=%d",
                int(reclaimable_mb), freelist_before, page_size,
            )
            result["reclaimable_bytes"] = reclaimable_bytes
            result["freelist_before"] = freelist_before
            if reclaimable_bytes < _SQLITE_STARTUP_RECLAIM_THRESHOLD_BYTES:
                return result
            # Try to free pages incrementally. On databases created with
            # auto_vacuum = NONE this returns success but does not actually
            # shrink the freelist — we detect that case below and recreate.
            cap = max(1, min(freelist_before, 50_000))
            conn.execute(f"PRAGMA incremental_vacuum({cap})")
            conn.commit()
            freelist_after = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            result["freelist_after"] = freelist_after
            if freelist_after < freelist_before:
                logger.info(
                    "SQLite startup vacuum complete freelist_before=%d freelist_after=%d freed=%d",
                    freelist_before, freelist_after, freelist_before - freelist_after,
                )
                result["action"] = "vacuum"
                return result
            logger.warning(
                "SQLite startup vacuum did not reclaim pages "
                "(auto_vacuum=NONE on legacy file?); recreating db"
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("SQLite startup heal failed: %s — recreating", exc)
        result["error"] = str(exc)
    # Fallback path: drop the file (and sidecars) so initialize() rebuilds
    # it from scratch with the right pragmas.
    try:
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = f"{db_path}{suffix}"
            if os.path.exists(path):
                os.remove(path)
        logger.warning(
            "SQLite deleted and will be recreated (Postgres is source of truth) path=%s",
            db_path,
        )
        result["action"] = "recreated"
    except Exception as remove_exc:
        logger.error("SQLite deletion failed: %s", remove_exc)
        result["action"] = "delete_failed"
        result["delete_error"] = str(remove_exc)
    return result


@dataclass(frozen=True)
class PersistenceConfig:
    enabled: bool = True
    backend: str = "sqlite"
    db_path: str = "/var/lib/auditlens/auditlens.db"
    enriched_retention_days: int = 30
    signals_retention_days: int = 30
    alerts_retention_days: int = 90
    audit_retention_days: int = 90
    db_max_bytes: int = 5 * 1024 * 1024 * 1024
    wal_max_bytes: int = 1024 * 1024 * 1024
    free_disk_warning_bytes: int = 1024 * 1024 * 1024
    free_disk_critical_bytes: int = 200 * 1024 * 1024
    adaptive_retention_min_hours: int = 1
    adaptive_retention_target_ratio: float = 0.90
    adaptive_retention_batch_rows: int = 5000
    adaptive_retention_max_batches: int = 20
    storage_warning_threshold: float = 0.80
    storage_critical_threshold: float = 0.90
    storage_emergency_threshold: float = 0.95
    rotation_retention_hours: int = 24
    rotation_target_ratio: float = 0.80
    rotation_copy_batch_rows: int = 5000

    @classmethod
    def from_env(cls) -> "PersistenceConfig":
        max_bytes = os.getenv("MAX_DB_SIZE_BYTES") or os.getenv("PERSISTENCE_DB_MAX_BYTES") or str(5 * 1024 * 1024 * 1024)
        return cls(
            enabled=os.getenv("PERSISTENCE_ENABLED", "true").lower() == "true",
            backend=os.getenv("PERSISTENCE_BACKEND", "sqlite"),
            db_path=os.getenv("PERSISTENCE_DB_PATH", "/var/lib/auditlens/auditlens.db"),
            enriched_retention_days=int(os.getenv("PERSISTENCE_ENRICHED_RETENTION_DAYS", "30")),
            signals_retention_days=int(os.getenv("PERSISTENCE_SIGNALS_RETENTION_DAYS", "30")),
            alerts_retention_days=int(os.getenv("PERSISTENCE_ALERTS_RETENTION_DAYS", "90")),
            audit_retention_days=int(os.getenv("PERSISTENCE_AUDIT_RETENTION_DAYS", "90")),
            db_max_bytes=int(max_bytes),
            wal_max_bytes=int(os.getenv("PERSISTENCE_WAL_MAX_BYTES", str(1024 * 1024 * 1024))),
            free_disk_warning_bytes=int(os.getenv("PERSISTENCE_FREE_DISK_WARNING_BYTES", str(1024 * 1024 * 1024))),
            free_disk_critical_bytes=int(os.getenv("PERSISTENCE_FREE_DISK_CRITICAL_BYTES", str(200 * 1024 * 1024))),
            adaptive_retention_min_hours=int(os.getenv("PERSISTENCE_ADAPTIVE_RETENTION_MIN_HOURS", "1")),
            adaptive_retention_target_ratio=float(os.getenv("PERSISTENCE_ADAPTIVE_RETENTION_TARGET_RATIO", "0.90")),
            adaptive_retention_batch_rows=int(os.getenv("PERSISTENCE_ADAPTIVE_RETENTION_BATCH_ROWS", "5000")),
            adaptive_retention_max_batches=int(os.getenv("PERSISTENCE_ADAPTIVE_RETENTION_MAX_BATCHES", "20")),
            storage_warning_threshold=float(os.getenv("PERSISTENCE_STORAGE_WARNING_THRESHOLD", "0.80")),
            storage_critical_threshold=float(os.getenv("PERSISTENCE_STORAGE_CRITICAL_THRESHOLD", "0.90")),
            storage_emergency_threshold=float(os.getenv("PERSISTENCE_STORAGE_EMERGENCY_THRESHOLD", "0.95")),
            rotation_retention_hours=int(os.getenv("PERSISTENCE_ROTATION_RETENTION_HOURS", "24")),
            rotation_target_ratio=float(os.getenv("PERSISTENCE_ROTATION_TARGET_RATIO", "0.80")),
            rotation_copy_batch_rows=int(os.getenv("PERSISTENCE_ROTATION_COPY_BATCH_ROWS", "5000")),
        )


class SQLiteProductStore:
    def __init__(self, config: PersistenceConfig):
        self.config = config
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._status: Dict[str, Any] = {
            "enabled": config.enabled,
            "healthy": False,
            "backend": config.backend,
            "db_path": config.db_path,
            "db_file_bytes": 0,
            "wal_file_bytes": 0,
            "current_db_size": 0,
            "max_db_size": config.db_max_bytes,
            "free_disk_bytes": 0,
            "db_max_bytes": config.db_max_bytes,
            "wal_max_bytes": config.wal_max_bytes,
            "storage_mode": "normal",
            "warning_threshold": config.storage_warning_threshold,
            "critical_threshold": config.storage_critical_threshold,
            "emergency_threshold": config.storage_emergency_threshold,
            "free_disk_warning_bytes": config.free_disk_warning_bytes,
            "free_disk_critical_bytes": config.free_disk_critical_bytes,
            "storage_status": "ok",
            "storage_reasons": [],
            "data_retention_mode": "bounded_hot_cache",
            "hot_cache_retention_hours": config.rotation_retention_hours,
            "archive_enabled": False,
            "data_loss_possible": True,
            "write_guard_active": False,
            "storage_degraded": False,
            "last_error": None,
            "last_write_at": None,
            "startup_count": 0,
            "last_cleanup_at": None,
            "last_cleanup_deleted_rows": 0,
            "last_cleanup_time_deleted_rows": 0,
            "last_cleanup_size_deleted_rows": 0,
            "last_cleanup_strategy": "none",
            "cleanup_status": "not_run",
            "cleanup_last_error": None,
            "size_cleanup_status": "not_run",
            "size_cleanup_last_error": None,
            "size_cleanup_pressure_bytes": 0,
            "size_cleanup_target_bytes": int(config.db_max_bytes * config.adaptive_retention_target_ratio),
            "sqlite_page_size": 0,
            "sqlite_freelist_pages": 0,
            "sqlite_reclaimable_bytes": 0,
            "last_vacuum_at": None,
            "last_vacuum_status": "not_used",
            "last_vacuum_error": None,
            "rotation_in_progress": False,
            "last_rotation_time": None,
            "rows_copied": 0,
            "rotation_duration_ms": 0,
            "rotation_total": 0,
            "rotation_status": "not_run",
            "rotation_last_error": None,
            "rotation_trigger": None,
            "last_rotation_failure_time": None,
            "rotation_retention_hours": config.rotation_retention_hours,
            "storage_write_dropped_total": 0,
            "adaptive_retention_min_hours": config.adaptive_retention_min_hours,
            "adaptive_retention_max_batches": config.adaptive_retention_max_batches,
            "size_cleanup_complete": True,
            "effective_retention_hours": {
                "enriched_events": config.enriched_retention_days * 24,
                "high_risk_events": config.signals_retention_days * 24,
                "denial_summaries": config.signals_retention_days * 24,
                "alerts": config.alerts_retention_days * 24,
                "api_audit_log": config.audit_retention_days * 24,
            },
            "last_checkpoint_at": None,
            "last_checkpoint_mode": None,
            "last_checkpoint_status": "not_run",
            "last_checkpoint_busy": 0,
            "last_checkpoint_log_frames": 0,
            "last_checkpoint_checkpointed_frames": 0,
            "last_checkpoint_error": None,
        }

    def initialize(self) -> None:
        if not self.config.enabled:
            self._status["healthy"] = False
            return
        if self.config.backend != "sqlite":
            # Postgres-only deployment: the durable store is Postgres
            # (accessed via DATABASE_URL through SQLAlchemy in
            # src/product/db_writer.py). The SQLite hot cache class only
            # makes sense in legacy demo mode; for any other backend the
            # initializer is a clean no-op rather than a crash.
            self._status["healthy"] = False
            self._status["backend"] = self.config.backend
            logger.info(
                "SQLite hot cache skipped (backend=%s) — Postgres is the durable store via SQLAlchemy.",
                self.config.backend,
            )
            return
        db_parent = os.path.dirname(self.config.db_path)
        if db_parent:
            os.makedirs(db_parent, exist_ok=True)
        self._conn = sqlite3.connect(self.config.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # auto_vacuum + max_page_count + temp_store=MEMORY must be applied
        # BEFORE any table exists on a fresh DB — otherwise auto_vacuum is
        # a silent no-op forever. heal_sqlite_on_startup() recreates the
        # file when the previous run left auto_vacuum=NONE.
        _apply_connection_pragmas(self._conn)
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()
        self._record_startup()
        self._status["healthy"] = True
        self.checkpoint_wal(mode="TRUNCATE")
        self._refresh_storage_status()

    def enforce_storage_bounds(self, trigger: str = "manual") -> Dict[str, Any]:
        """Refresh storage state and rotate if the hot cache is above its hard cap."""
        assert self._conn is not None
        with self._lock:
            self._refresh_storage_status()
            if self._storage_bytes() <= self.config.db_max_bytes:
                return dict(self._status)
            try:
                logger.warning(
                    "SQLite hot-cache storage bound enforcement triggered: trigger=%s current_size=%d max_size=%d",
                    trigger,
                    self._storage_bytes(),
                    self.config.db_max_bytes,
                )
                self._rotate_hot_cache_unlocked(trigger=trigger)
            except Exception as exc:
                self._mark_storage_degraded_unlocked(str(exc), trigger=trigger)
            self._refresh_storage_status()
            return dict(self._status)

    def _create_schema(self) -> None:
        assert self._conn is not None
        self._create_schema_on(self._conn)

    def _create_schema_on(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS enriched_events (
                event_id TEXT PRIMARY KEY,
                event_time TEXT,
                ingested_at TEXT,
                organization_id TEXT,
                environment_id TEXT,
                cluster_id TEXT,
                principal_raw TEXT,
                principal_normalized TEXT,
                principal_type TEXT,
                method_name TEXT,
                resource_name TEXT,
                criticality TEXT,
                source_topic TEXT,
                source_partition INTEGER,
                source_offset INTEGER,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_enriched_time ON enriched_events(event_time);
            CREATE INDEX IF NOT EXISTS idx_enriched_scope ON enriched_events(organization_id, environment_id, cluster_id);
            CREATE INDEX IF NOT EXISTS idx_enriched_principal ON enriched_events(principal_normalized);

            CREATE TABLE IF NOT EXISTS high_risk_events (
                event_id TEXT PRIMARY KEY,
                event_time TEXT,
                organization_id TEXT,
                environment_id TEXT,
                cluster_id TEXT,
                principal_normalized TEXT,
                method_name TEXT,
                resource_name TEXT,
                source_partition INTEGER,
                source_offset INTEGER,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS denial_summaries (
                summary_id TEXT PRIMARY KEY,
                window_end TEXT,
                organization_id TEXT,
                environment_id TEXT,
                cluster_id TEXT,
                principal_normalized TEXT,
                method_name TEXT,
                resource_name TEXT,
                denial_count INTEGER,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                event_time TEXT,
                severity TEXT,
                organization_id TEXT,
                environment_id TEXT,
                cluster_id TEXT,
                principal_normalized TEXT,
                alert_type TEXT,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                happened_at TEXT NOT NULL,
                actor_id TEXT,
                role TEXT,
                action TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                remote_addr TEXT,
                user_agent TEXT,
                filters_json TEXT,
                denied_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS runtime_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def _record_startup(self) -> None:
        assert self._conn is not None
        current = self._get_meta_int("startup_count") + 1
        self._set_meta("startup_count", str(current))
        self._set_meta("last_startup_at", utc_now_iso())
        self._conn.commit()
        self._status["startup_count"] = current

    def _get_meta_int(self, key: str) -> int:
        assert self._conn is not None
        row = self._conn.execute("SELECT value FROM runtime_meta WHERE key = ?", (key,)).fetchone()
        return int(row["value"]) if row else 0

    def _set_meta(self, key: str, value: str) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO runtime_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def health(self) -> Dict[str, Any]:
        self._refresh_storage_status()
        return dict(self._status)

    def get_runtime_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        assert self._conn is not None
        row = self._conn.execute("SELECT value FROM runtime_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_runtime_meta(self, key: str, value: str) -> None:
        assert self._conn is not None
        with self._lock:
            self._set_meta(key, value)
            self._conn.commit()
            self._status["last_write_at"] = utc_now_iso()
            self._refresh_storage_status()

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        assert self._conn is not None
        with self._lock:
            # Skip the per-write storage refresh: it's PRAGMA + file stat heavy
            # and dominates write latency at hundreds of msg/s. The cleanup
            # loop, health check, and explicit enforce_storage_bounds() callers
            # all refresh status separately. Rotation safety still works because
            # _drop_write_if_emergency() refreshes status on the emergency path.
            self._conn.execute(sql, params)
            self._conn.commit()
            self._status["last_write_at"] = utc_now_iso()

    # Throttle the per-write status refresh: cleanup loop, health check, and
    # enforce_storage_bounds() refresh status on their own cadence; the hot
    # write path only needs to verify periodically.
    _STATUS_REFRESH_INTERVAL_SECONDS = 5.0
    _last_status_refresh_monotonic = 0.0

    def _drop_write_if_emergency(self, priority: str) -> bool:
        with self._lock:
            now = time.monotonic()
            if now - self._last_status_refresh_monotonic >= self._STATUS_REFRESH_INTERVAL_SECONDS:
                self._refresh_storage_status()
                if self._storage_bytes() > self.config.db_max_bytes:
                    try:
                        self._rotate_hot_cache_unlocked(trigger="write")
                    except Exception as exc:
                        self._mark_storage_degraded_unlocked(str(exc), trigger="write")
                    self._refresh_storage_status()
                self._last_status_refresh_monotonic = now
        if self._storage_mode() != "emergency" and not self._status.get("storage_degraded"):
            return False
        if priority == "high":
            return False
        self._status["storage_write_dropped_total"] = int(self._status.get("storage_write_dropped_total") or 0) + 1
        self._status["last_write_at"] = utc_now_iso()
        return True

    def persist_enriched_event(self, event: Dict[str, Any], source_topic: str, source_partition: int, source_offset: int) -> None:
        priority = "high" if str(event.get("criticality", "")).upper() in {"HIGH", "CRITICAL"} else "low"
        if self._drop_write_if_emergency(priority):
            return
        payload = orjson.dumps(event).decode("utf-8")
        self._write(
            """
            INSERT INTO enriched_events (
                event_id, event_time, ingested_at, organization_id, environment_id, cluster_id,
                principal_raw, principal_normalized, principal_type, method_name, resource_name,
                criticality, source_topic, source_partition, source_offset, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                event_time=excluded.event_time,
                ingested_at=excluded.ingested_at,
                organization_id=excluded.organization_id,
                environment_id=excluded.environment_id,
                cluster_id=excluded.cluster_id,
                principal_raw=excluded.principal_raw,
                principal_normalized=excluded.principal_normalized,
                principal_type=excluded.principal_type,
                method_name=excluded.method_name,
                resource_name=excluded.resource_name,
                criticality=excluded.criticality,
                source_topic=excluded.source_topic,
                source_partition=excluded.source_partition,
                source_offset=excluded.source_offset,
                payload_json=excluded.payload_json
            """,
            (
                event.get("id"),
                event.get("time"),
                utc_now_iso(),
                event.get("organization_id"),
                event.get("environment_id"),
                event.get("cluster_id"),
                event.get("principal_raw"),
                event.get("principal_normalized"),
                event.get("principal_type"),
                event.get("methodName"),
                event.get("resourceName") or event.get("authzResourceName"),
                event.get("criticality"),
                source_topic,
                source_partition,
                source_offset,
                payload,
            ),
        )

    def persist_high_risk_event(self, event: Dict[str, Any], source_partition: int, source_offset: int) -> None:
        if self._drop_write_if_emergency("high"):
            return
        payload = orjson.dumps(event).decode("utf-8")
        self._write(
            """
            INSERT INTO high_risk_events (
                event_id, event_time, organization_id, environment_id, cluster_id,
                principal_normalized, method_name, resource_name, source_partition,
                source_offset, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                event_time=excluded.event_time,
                organization_id=excluded.organization_id,
                environment_id=excluded.environment_id,
                cluster_id=excluded.cluster_id,
                principal_normalized=excluded.principal_normalized,
                method_name=excluded.method_name,
                resource_name=excluded.resource_name,
                source_partition=excluded.source_partition,
                source_offset=excluded.source_offset,
                payload_json=excluded.payload_json
            """,
            (
                event.get("id"),
                event.get("time"),
                event.get("organization_id"),
                event.get("environment_id"),
                event.get("cluster_id"),
                event.get("principal_normalized"),
                event.get("methodName"),
                event.get("resourceName") or event.get("authzResourceName"),
                source_partition,
                source_offset,
                payload,
            ),
        )

    def persist_denial_summary(self, summary: Dict[str, Any]) -> None:
        if self._drop_write_if_emergency("low"):
            return
        payload = orjson.dumps(summary).decode("utf-8")
        self._write(
            """
            INSERT INTO denial_summaries (
                summary_id, window_end, organization_id, environment_id, cluster_id,
                principal_normalized, method_name, resource_name, denial_count, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(summary_id) DO UPDATE SET
                window_end=excluded.window_end,
                organization_id=excluded.organization_id,
                environment_id=excluded.environment_id,
                cluster_id=excluded.cluster_id,
                principal_normalized=excluded.principal_normalized,
                method_name=excluded.method_name,
                resource_name=excluded.resource_name,
                denial_count=excluded.denial_count,
                payload_json=excluded.payload_json
            """,
            (
                summary.get("id"),
                summary.get("window_end") or summary.get("time"),
                _first_or_none(summary.get("organization_ids")),
                _first_or_none(summary.get("environment_ids")),
                _first_or_none(summary.get("cluster_ids")),
                summary.get("principal_normalized"),
                summary.get("methodName"),
                summary.get("resource_name"),
                summary.get("denial_count"),
                payload,
            ),
        )

    def persist_alert(self, alert: Dict[str, Any]) -> None:
        if self._drop_write_if_emergency("high"):
            return
        alert_id = alert.get("id") or alert.get("source_event_id") or f"{alert.get('alert_type')}:{alert.get('event_time')}:{alert.get('principal')}"
        payload = orjson.dumps(alert).decode("utf-8")
        self._write(
            """
            INSERT INTO alerts (
                alert_id, event_time, severity, organization_id, environment_id, cluster_id,
                principal_normalized, alert_type, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alert_id) DO UPDATE SET
                event_time=excluded.event_time,
                severity=excluded.severity,
                organization_id=excluded.organization_id,
                environment_id=excluded.environment_id,
                cluster_id=excluded.cluster_id,
                principal_normalized=excluded.principal_normalized,
                alert_type=excluded.alert_type,
                payload_json=excluded.payload_json
            """,
            (
                alert_id,
                alert.get("event_time"),
                alert.get("severity") or alert.get("criticality"),
                alert.get("organization_id") or _first_or_none(alert.get("organization_ids")),
                alert.get("environment_id") or _first_or_none(alert.get("environment_ids")),
                alert.get("cluster_id") or _first_or_none(alert.get("cluster_ids")),
                alert.get("principal_normalized") or alert.get("principal"),
                alert.get("alert_type") or alert.get("methodName"),
                payload,
            ),
        )

    def record_api_audit(
        self,
        actor_id: Optional[str],
        role: Optional[str],
        action: str,
        endpoint: str,
        status_code: int,
        remote_addr: Optional[str],
        user_agent: Optional[str],
        filters: Optional[Dict[str, Any]],
        denied_reason: Optional[str] = None,
    ) -> None:
        if self._drop_write_if_emergency("low"):
            return
        self._write(
            """
            INSERT INTO api_audit_log (
                happened_at, actor_id, role, action, endpoint, status_code, remote_addr,
                user_agent, filters_json, denied_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                actor_id,
                role,
                action,
                endpoint,
                status_code,
                remote_addr,
                user_agent,
                orjson.dumps(filters or {}).decode("utf-8"),
                denied_reason,
            ),
        )

    def query_enriched(self, filters: Dict[str, Any], actor, limit: int) -> list[dict]:
        return self._query_records("enriched_events", "event_time", filters, actor, limit)

    def query_high_risk(self, filters: Dict[str, Any], actor, limit: int) -> list[dict]:
        return self._query_records("high_risk_events", "event_time", filters, actor, limit)

    def query_denials(self, actor, limit: int) -> list[dict]:
        return self._query_records("denial_summaries", "window_end", {}, actor, limit)

    def _query_records(self, table: str, time_column: str, filters: Dict[str, Any], actor, limit: int) -> list[dict]:
        assert self._conn is not None
        where = []
        params: list[Any] = []
        if actor and "*" not in actor.organizations:
            where.append(f"(organization_id IN ({','.join('?' for _ in actor.organizations)}))")
            params.extend(actor.organizations)
        if actor and "*" not in actor.environments:
            where.append(f"(environment_id IN ({','.join('?' for _ in actor.environments)}))")
            params.extend(actor.environments)
        if actor and "*" not in actor.clusters:
            where.append(f"(cluster_id IN ({','.join('?' for _ in actor.clusters)}))")
            params.extend(actor.clusters)

        if filters.get("criticality"):
            where.append("criticality = ?")
            params.append(filters["criticality"])
        if filters.get("principal"):
            where.append("principal_normalized LIKE ?")
            params.append(f"%{filters['principal']}%")
        if filters.get("method"):
            where.append("method_name LIKE ?")
            params.append(f"%{filters['method']}%")
        if filters.get("resource"):
            where.append("resource_name LIKE ?")
            params.append(f"%{filters['resource']}%")
        if filters.get("time_from"):
            where.append(f"{time_column} >= ?")
            params.append(filters["time_from"])
        if filters.get("time_to"):
            where.append(f"{time_column} <= ?")
            params.append(filters["time_to"])
        if filters.get("q"):
            where.append("(payload_json LIKE ? OR method_name LIKE ? OR resource_name LIKE ? OR principal_normalized LIKE ?)")
            wildcard = f"%{filters['q']}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        select_columns = "payload_json"
        if table in {"enriched_events", "high_risk_events"}:
            select_columns = "payload_json, source_topic, source_partition, source_offset"
        sql = f"SELECT {select_columns} FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {time_column} DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            payload = orjson.loads(row["payload_json"])
            if "source_partition" in row.keys():
                payload["_auditlens_source"] = {
                    "topic": row["source_topic"],
                    "partition": row["source_partition"],
                    "offset": row["source_offset"],
                }
            results.append(payload)
        return results

    def cleanup_expired(self) -> int:
        assert self._conn is not None
        with self._lock:
            try:
                self._cleanup_batches_remaining = self._cleanup_batch_budget()
                time_deleted_rows = self._cleanup_by_configured_retention()
                self._conn.commit()
                self._refresh_storage_status()

                size_deleted_rows = 0
                strategy = "time_retention"
                if self._storage_bytes() > self._size_cleanup_target_bytes():
                    strategy = "time_retention+size_pressure"
                    size_deleted_rows = self._cleanup_for_size_pressure()
                    self._conn.commit()
                    if size_deleted_rows > 0:
                        self._checkpoint_wal_unlocked(mode="TRUNCATE")
                if self._storage_bytes() > self.config.db_max_bytes:
                    strategy = f"{strategy}+rotation"
                    self._rotate_hot_cache_unlocked(trigger="cleanup")

                deleted_rows = time_deleted_rows + size_deleted_rows
                self._status["last_cleanup_at"] = utc_now_iso()
                self._status["last_cleanup_deleted_rows"] = deleted_rows
                self._status["last_cleanup_time_deleted_rows"] = time_deleted_rows
                self._status["last_cleanup_size_deleted_rows"] = size_deleted_rows
                self._status["last_cleanup_strategy"] = strategy
                self._status["cleanup_status"] = "success"
                self._status["cleanup_last_error"] = None
                self._refresh_storage_status()
                # After non-trivial deletions, hand the released pages back
                # to the OS proactively so the file size tracks the row
                # count instead of monotonically growing.
                if deleted_rows >= 1000:
                    self._run_incremental_vacuum_unlocked(
                        max_pages=self._VACUUM_BATCH_PAGES_PER_CLEANUP,
                        trigger=f"cleanup:{deleted_rows}",
                    )
                self._vacuum_if_useful_unlocked()
                return deleted_rows
            except Exception as exc:
                self._status["last_cleanup_at"] = utc_now_iso()
                self._status["cleanup_status"] = "failure"
                self._status["cleanup_last_error"] = str(exc)
                self._refresh_storage_status()
                raise

    def checkpoint_wal(self, mode: str = "PASSIVE") -> Dict[str, Any]:
        assert self._conn is not None
        checkpoint_mode = str(mode).upper()
        with self._lock:
            try:
                return self._checkpoint_wal_unlocked(checkpoint_mode)
            except Exception as exc:
                self._status["last_checkpoint_at"] = utc_now_iso()
                self._status["last_checkpoint_mode"] = checkpoint_mode
                self._status["last_checkpoint_status"] = "failure"
                self._status["last_checkpoint_error"] = str(exc)
                self._refresh_storage_status()
                raise

    def _cleanup_by_configured_retention(self) -> int:
        deleted_rows = 0
        for table, time_column, retention_days in self._retention_tables():
            deleted_rows += self._delete_older_than(table, time_column, retention_days)
            self._set_effective_retention_hours(table, retention_days * 24)
        self._status["size_cleanup_status"] = "not_needed"
        self._status["size_cleanup_last_error"] = None
        return deleted_rows

    def _cleanup_for_size_pressure(self) -> int:
        assert self._conn is not None
        target_bytes = self._size_cleanup_target_bytes()
        pressure_bytes = max(0, self._storage_bytes() - target_bytes)
        self._status["size_cleanup_pressure_bytes"] = pressure_bytes
        self._status["size_cleanup_target_bytes"] = target_bytes
        self._status["size_cleanup_status"] = "running"
        deleted_rows = 0

        try:
            for table, time_column, retention_days in self._retention_tables_for_storage_mode():
                if self._storage_bytes() <= target_bytes:
                    break
                effective_hours = self._adaptive_retention_hours(table, time_column, retention_days)
                self._set_effective_retention_hours(table, effective_hours)
                table_deleted_rows = self._delete_older_than_hours_batched(table, time_column, effective_hours)
                deleted_rows += table_deleted_rows
                if table_deleted_rows > 0:
                    self._checkpoint_wal_best_effort_unlocked(mode="TRUNCATE")

            if self._storage_bytes() > target_bytes:
                deleted_rows += self._delete_oldest_batches(target_bytes)

            self._status["size_cleanup_complete"] = self._storage_bytes() <= target_bytes
            self._status["size_cleanup_status"] = "success" if self._status["size_cleanup_complete"] else "partial"
            self._status["size_cleanup_last_error"] = None
            return deleted_rows
        except Exception as exc:
            self._status["size_cleanup_status"] = "failure"
            self._status["size_cleanup_last_error"] = str(exc)
            raise

    def _retention_tables(self) -> list[tuple[str, str, int]]:
        return [
            ("enriched_events", "event_time", self.config.enriched_retention_days),
            ("high_risk_events", "event_time", self.config.signals_retention_days),
            ("denial_summaries", "window_end", self.config.signals_retention_days),
            ("alerts", "event_time", self.config.alerts_retention_days),
            ("api_audit_log", "happened_at", self.config.audit_retention_days),
        ]

    def _retention_tables_for_storage_mode(self) -> list[tuple[str, str, int]]:
        tables = self._retention_tables()
        if self._storage_mode() not in {"critical", "emergency"}:
            return tables
        assert self._conn is not None
        return sorted(
            tables,
            key=lambda spec: self._conn.execute(f"SELECT COUNT(*) AS count FROM {spec[0]}").fetchone()["count"],
            reverse=True,
        )

    def _cleanup_batch_budget(self) -> int:
        base = max(1, self.config.adaptive_retention_max_batches)
        mode = self._storage_mode()
        if mode == "warning":
            return base * 2
        if mode == "critical":
            return base * 4
        if mode == "emergency":
            return base * 8
        return base

    def _rotation_tables(self) -> list[tuple[str, str]]:
        return [
            ("high_risk_events", "event_time"),
            ("alerts", "event_time"),
            ("enriched_events", "event_time"),
            ("denial_summaries", "window_end"),
            ("api_audit_log", "happened_at"),
        ]

    def _rotate_hot_cache_unlocked(self, trigger: str = "manual") -> None:
        assert self._conn is not None
        if self._storage_bytes() <= self.config.db_max_bytes:
            return

        started = time.monotonic()
        started_at = utc_now_iso()
        db_path = self.config.db_path
        db_parent = os.path.dirname(db_path) or "."
        rotation_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        new_path = os.path.join(db_parent, f".auditlens.db.rotating.{rotation_id}")
        old_path = os.path.join(db_parent, f".auditlens.db.old.{rotation_id}")
        copied_rows = 0
        self._status["rotation_in_progress"] = True
        self._status["rotation_status"] = "running"
        self._status["rotation_last_error"] = None
        self._status["rotation_trigger"] = trigger
        logger.warning(
            "SQLite hot-cache rotation started: trigger=%s current_size=%d max_size=%d retention_hours=%d",
            trigger,
            self._storage_bytes(),
            self.config.db_max_bytes,
            self.config.rotation_retention_hours,
        )

        try:
            self._conn.commit()
            self._checkpoint_wal_best_effort_unlocked(mode="TRUNCATE")
            copy_cutoff = (
                datetime.now(timezone.utc) - timedelta(hours=max(1, self.config.rotation_retention_hours))
            ).isoformat().replace("+00:00", "Z")
            target_bytes = max(1, int(self.config.db_max_bytes * min(0.95, max(0.10, self.config.rotation_target_ratio))))

            new_conn = sqlite3.connect(new_path)
            new_conn.row_factory = sqlite3.Row
            new_conn.execute("PRAGMA journal_mode=DELETE")
            # Apply pragmas BEFORE creating the schema so auto_vacuum is
            # active for the new file. The post-rotation file is the
            # primary fix for any legacy DBs stuck with auto_vacuum=NONE.
            _apply_connection_pragmas(new_conn)
            new_conn.execute("PRAGMA synchronous=FULL")
            self._create_schema_on(new_conn)

            for table, time_column in self._rotation_tables():
                if os.path.getsize(new_path) >= target_bytes:
                    break
                copied_rows += self._copy_recent_rows_for_rotation(
                    new_conn,
                    table,
                    time_column,
                    copy_cutoff,
                    target_bytes,
                )
            if copied_rows == 0:
                for table, time_column in self._rotation_tables():
                    if os.path.getsize(new_path) >= target_bytes:
                        break
                    copied_rows += self._copy_recent_rows_for_rotation(
                        new_conn,
                        table,
                        time_column,
                        "0001-01-01T00:00:00Z",
                        target_bytes,
                    )

            new_conn.commit()
            new_conn.close()

            if os.path.getsize(new_path) > self.config.db_max_bytes:
                os.remove(new_path)
                raise RuntimeError("rotation output exceeded configured max size")

            self._conn.close()
            self._conn = None
            os.replace(db_path, old_path)
            os.replace(new_path, db_path)
            self._remove_sqlite_sidecars(db_path)
            self._remove_sqlite_sidecars(old_path)
            if os.path.exists(old_path):
                os.remove(old_path)

            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            _apply_connection_pragmas(self._conn)
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._status["rows_copied"] = copied_rows
            self._status["last_rotation_time"] = started_at
            self._status["rotation_duration_ms"] = int((time.monotonic() - started) * 1000)
            self._status["rotation_total"] = int(self._status.get("rotation_total") or 0) + 1
            self._status["rotation_status"] = "success"
            self._status["rotation_last_error"] = None
            self._status["storage_degraded"] = False
            self._status["write_guard_active"] = False
            self._status["rotation_in_progress"] = False
            self._refresh_storage_status()
            logger.warning(
                "SQLite hot-cache rotation completed: trigger=%s rows_copied=%d duration_ms=%d current_size=%d max_size=%d",
                trigger,
                copied_rows,
                self._status["rotation_duration_ms"],
                self._status["current_db_size"],
                self.config.db_max_bytes,
            )
        except Exception as exc:
            self._status["rotation_duration_ms"] = int((time.monotonic() - started) * 1000)
            self._status["rotation_status"] = "failure"
            self._status["rotation_last_error"] = str(exc)
            self._status["last_rotation_failure_time"] = utc_now_iso()
            self._status["rotation_trigger"] = trigger
            self._status["rotation_in_progress"] = False
            if self._conn is None and os.path.exists(db_path):
                self._conn = sqlite3.connect(db_path, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
            if os.path.exists(new_path):
                os.remove(new_path)
            self._refresh_storage_status()
            self._mark_storage_degraded_unlocked(str(exc), trigger=trigger)
            logger.error(
                "SQLite hot-cache rotation failed: trigger=%s duration_ms=%d error=%s",
                trigger,
                self._status["rotation_duration_ms"],
                exc,
            )
            raise

    def _mark_storage_degraded_unlocked(self, error: str, trigger: str) -> None:
        self._status["rotation_status"] = "failure"
        self._status["rotation_last_error"] = error
        self._status["last_rotation_failure_time"] = utc_now_iso()
        self._status["rotation_trigger"] = trigger
        self._status["storage_degraded"] = True
        self._status["write_guard_active"] = True
        self._status["data_loss_possible"] = True
        self._status["storage_mode"] = "emergency"

    def _copy_recent_rows_for_rotation(
        self,
        new_conn: sqlite3.Connection,
        table: str,
        time_column: str,
        copy_cutoff: str,
        target_bytes: int,
    ) -> int:
        assert self._conn is not None
        columns = [row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()]
        column_sql = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})"
        copied_rows = 0
        batch_rows = max(1, self.config.rotation_copy_batch_rows)
        offset = 0

        while os.path.getsize(new_conn.execute("PRAGMA database_list").fetchone()["file"]) < target_bytes:
            rows = self._conn.execute(
                f"""
                SELECT {column_sql}
                FROM {table}
                WHERE {time_column} IS NOT NULL
                  AND {time_column} >= ?
                ORDER BY {time_column} DESC
                LIMIT ? OFFSET ?
                """,
                (copy_cutoff, batch_rows, offset),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                if os.path.getsize(new_conn.execute("PRAGMA database_list").fetchone()["file"]) >= target_bytes:
                    break
                new_conn.execute(insert_sql, tuple(row[column] for column in columns))
                copied_rows += 1
            new_conn.commit()
            if len(rows) < batch_rows:
                break
            offset += batch_rows
        return copied_rows

    def _remove_sqlite_sidecars(self, db_path: str) -> None:
        for suffix in ("-wal", "-shm"):
            sidecar = f"{db_path}{suffix}"
            if os.path.exists(sidecar):
                os.remove(sidecar)

    def _delete_older_than(self, table: str, time_column: str, days: int) -> int:
        assert self._conn is not None
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        cursor = self._conn.execute(f"DELETE FROM {table} WHERE {time_column} < ?", (cutoff,))
        return cursor.rowcount if cursor.rowcount is not None else 0

    def _delete_older_than_hours(self, table: str, time_column: str, hours: int) -> int:
        assert self._conn is not None
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        cursor = self._conn.execute(f"DELETE FROM {table} WHERE {time_column} < ?", (cutoff,))
        return cursor.rowcount if cursor.rowcount is not None else 0

    def _delete_older_than_hours_batched(self, table: str, time_column: str, hours: int) -> int:
        assert self._conn is not None
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        deleted_rows = 0
        batch_rows = max(1, self.config.adaptive_retention_batch_rows)
        while True:
            if not self._consume_cleanup_batch_budget():
                break
            cursor = self._conn.execute(
                f"""
                DELETE FROM {table}
                WHERE rowid IN (
                    SELECT rowid FROM {table}
                    WHERE {time_column} IS NOT NULL
                      AND {time_column} < ?
                    ORDER BY {time_column} ASC
                    LIMIT ?
                )
                """,
                (cutoff, batch_rows),
            )
            rowcount = cursor.rowcount if cursor.rowcount is not None else 0
            deleted_rows += rowcount
            if rowcount == 0:
                break
            self._conn.commit()
            self._checkpoint_wal_best_effort_unlocked(mode="TRUNCATE")
            if rowcount < batch_rows:
                break
        return deleted_rows

    def _delete_oldest_batches(self, target_bytes: int) -> int:
        assert self._conn is not None
        deleted_rows = 0
        batch_rows = max(1, self.config.adaptive_retention_batch_rows)
        min_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max(1, self.config.adaptive_retention_min_hours))
        ).isoformat().replace("+00:00", "Z")
        for table, time_column, _ in self._retention_tables():
            while self._storage_bytes() > target_bytes:
                if not self._consume_cleanup_batch_budget():
                    return deleted_rows
                cursor = self._conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE rowid IN (
                        SELECT rowid FROM {table}
                        WHERE {time_column} IS NOT NULL
                          AND {time_column} < ?
                        ORDER BY {time_column} ASC
                        LIMIT ?
                    )
                    """,
                    (min_cutoff, batch_rows),
                )
                rowcount = cursor.rowcount if cursor.rowcount is not None else 0
                deleted_rows += rowcount
                if rowcount < batch_rows:
                    break
                self._conn.commit()
                self._checkpoint_wal_best_effort_unlocked(mode="TRUNCATE")
        return deleted_rows

    def _adaptive_retention_hours(self, table: str, time_column: str, configured_days: int) -> int:
        assert self._conn is not None
        configured_hours = configured_days * 24
        min_hours = max(1, self.config.adaptive_retention_min_hours)
        newest = self._conn.execute(f"SELECT MAX({time_column}) AS newest FROM {table}").fetchone()
        newest_time = _parse_utc(newest["newest"] if newest else None)
        if newest_time is None:
            return configured_hours

        pressure_ratio = self._storage_bytes() / max(1, self._size_cleanup_target_bytes())
        min_ratio = {"normal": 0.50, "warning": 0.25, "critical": 0.10, "emergency": 0.02}.get(self._storage_mode(), 0.10)
        retention_ratio = max(min_ratio, min(0.90, 1 / pressure_ratio))
        adaptive_hours = int(configured_hours * retention_ratio)
        newest_age_hours = int((datetime.now(timezone.utc) - newest_time).total_seconds() // 3600)
        return max(min_hours, min(configured_hours, adaptive_hours, max(min_hours, newest_age_hours + adaptive_hours)))

    def _set_effective_retention_hours(self, table: str, hours: int) -> None:
        effective = dict(self._status.get("effective_retention_hours") or {})
        effective[table] = int(hours)
        self._status["effective_retention_hours"] = effective

    def _consume_cleanup_batch_budget(self) -> bool:
        remaining = int(getattr(self, "_cleanup_batches_remaining", self.config.adaptive_retention_max_batches))
        if remaining <= 0:
            return False
        self._cleanup_batches_remaining = remaining - 1
        return True

    def _storage_bytes(self) -> int:
        db_path = self.config.db_path
        wal_path = f"{db_path}-wal"
        db_file_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else int(self._status.get("db_file_bytes") or 0)
        wal_file_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else int(self._status.get("wal_file_bytes") or 0)
        return db_file_bytes + wal_file_bytes

    def _storage_mode(self) -> str:
        current_size = self._storage_bytes()
        max_size = max(1, self.config.db_max_bytes)
        ratio = current_size / max_size
        if ratio >= self.config.storage_emergency_threshold:
            return "emergency"
        if ratio >= self.config.storage_critical_threshold:
            return "critical"
        if ratio >= self.config.storage_warning_threshold:
            return "warning"
        return "normal"

    def _size_cleanup_target_bytes(self) -> int:
        ratio = min(1.0, max(0.10, self.config.adaptive_retention_target_ratio))
        return max(1, int(self.config.db_max_bytes * ratio))

    def _checkpoint_wal_unlocked(self, mode: str = "PASSIVE") -> Dict[str, Any]:
        assert self._conn is not None
        checkpoint_mode = str(mode).upper()
        busy, log_frames, checkpointed_frames = self._conn.execute(
            f"PRAGMA wal_checkpoint({checkpoint_mode})"
        ).fetchone()
        result = {
            "status": "success",
            "mode": checkpoint_mode,
            "busy": int(busy),
            "log_frames": int(log_frames),
            "checkpointed_frames": int(checkpointed_frames),
            "at": utc_now_iso(),
        }
        self._status["last_checkpoint_at"] = result["at"]
        self._status["last_checkpoint_mode"] = checkpoint_mode
        self._status["last_checkpoint_status"] = "success"
        self._status["last_checkpoint_busy"] = result["busy"]
        self._status["last_checkpoint_log_frames"] = result["log_frames"]
        self._status["last_checkpoint_checkpointed_frames"] = result["checkpointed_frames"]
        self._status["last_checkpoint_error"] = None
        self._refresh_storage_status()
        return result

    def _checkpoint_wal_best_effort_unlocked(self, mode: str = "PASSIVE") -> None:
        try:
            self._checkpoint_wal_unlocked(mode=mode)
        except sqlite3.OperationalError as exc:
            self._status["last_checkpoint_at"] = utc_now_iso()
            self._status["last_checkpoint_mode"] = str(mode).upper()
            self._status["last_checkpoint_status"] = "skipped"
            self._status["last_checkpoint_error"] = str(exc)

    # Auto-vacuum threshold: 100 MB reclaimable. With incremental_vacuum
    # the cost is proportional to freed pages (not file size), so we run
    # earlier and more often to keep the freelist from accumulating.
    _VACUUM_RECLAIM_THRESHOLD_BYTES = 100 * 1024 * 1024
    # Pages freed per cleanup pass. 5000 pages × 4 KB ≈ 20 MB — small
    # enough to be near-instant, big enough to dominate steady-state churn.
    _VACUUM_BATCH_PAGES_PER_CLEANUP = 5000

    def vacuum(self) -> Dict[str, Any]:
        """Run a SQLite incremental vacuum. Public entry point for /admin/vacuum."""
        with self._lock:
            return self._vacuum_unlocked(trigger="manual")

    def _run_incremental_vacuum_unlocked(self, *, max_pages: int, trigger: str) -> None:
        """Bounded incremental vacuum used as a steady-state cleanup hook.

        Unlike ``_vacuum_unlocked`` which logs and surfaces a structured
        result, this variant is deliberately quiet — it's called every
        cleanup cycle and only matters when something visible reclaims.
        """
        assert self._conn is not None
        try:
            freelist = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            if freelist <= 0:
                return
            cap = max(1, min(freelist, int(max_pages)))
            self._conn.execute(f"PRAGMA incremental_vacuum({cap})")
            self._conn.commit()
            self._refresh_storage_status()
            logger.info(
                "SQLite incremental_vacuum trigger=%s freed_pages<=%d",
                trigger, cap,
            )
        except Exception as exc:
            logger.debug("incremental_vacuum hook failed trigger=%s: %s", trigger, exc)

    def _vacuum_if_useful_unlocked(self) -> None:
        reclaimable = int(self._status.get("sqlite_reclaimable_bytes") or 0)
        storage_mode = str(self._status.get("storage_mode") or "normal")
        should_vacuum = (
            reclaimable >= self._VACUUM_RECLAIM_THRESHOLD_BYTES
            or storage_mode in {"critical", "emergency"}
        )
        if not should_vacuum:
            return
        self._vacuum_unlocked(trigger=f"auto:{storage_mode}")

    def _vacuum_unlocked(self, *, trigger: str) -> Dict[str, Any]:
        """Incremental VACUUM. Full ``VACUUM`` rebuilds the entire DB into a
        temp file ~2x the source size, which fails on the container's
        100 MB ``/tmp`` tmpfs. ``PRAGMA incremental_vacuum`` only frees
        already-released pages and never needs more than freelist-sized
        scratch, so it works regardless of tmpfs sizing.

        For legacy databases created with ``auto_vacuum = NONE`` this
        will silently do nothing — startup heal handles those by
        recreating the file."""
        assert self._conn is not None
        before_bytes = int(self._status.get("db_file_bytes") or 0)
        before_reclaimable = int(self._status.get("sqlite_reclaimable_bytes") or 0)
        page_size = int(self._status.get("sqlite_page_size") or 0) or int(
            self._conn.execute("PRAGMA page_size").fetchone()[0] or 4096
        )
        freelist_before = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
        started = time.monotonic()
        try:
            self._checkpoint_wal_best_effort_unlocked(mode="TRUNCATE")
            self._conn.commit()
            cap = max(1, min(freelist_before, 50_000))
            self._conn.execute(f"PRAGMA incremental_vacuum({cap})")
            self._conn.commit()
            duration_ms = int((time.monotonic() - started) * 1000)
            freelist_after = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            self._status["last_vacuum_at"] = utc_now_iso()
            self._status["last_vacuum_status"] = "success"
            self._status["last_vacuum_error"] = None
            self._refresh_storage_status()
            after_bytes = int(self._status.get("db_file_bytes") or 0)
            reclaimed = max(0, before_bytes - after_bytes)
            freed_pages = max(0, freelist_before - freelist_after)
            logger.info(
                "SQLite incremental_vacuum complete trigger=%s freed_pages=%d "
                "before_bytes=%d after_bytes=%d reclaimed_bytes=%d duration_ms=%d",
                trigger, freed_pages, before_bytes, after_bytes, reclaimed, duration_ms,
            )
            return {
                "status": "success",
                "trigger": trigger,
                "mode": "incremental",
                "before_bytes": before_bytes,
                "after_bytes": after_bytes,
                "before_reclaimable_bytes": before_reclaimable,
                "reclaimed_bytes": reclaimed,
                "freed_pages": freed_pages,
                "page_size": page_size,
                "duration_ms": duration_ms,
                "at": self._status["last_vacuum_at"],
            }
        except Exception as exc:
            self._status["last_vacuum_at"] = utc_now_iso()
            self._status["last_vacuum_status"] = "failure"
            self._status["last_vacuum_error"] = str(exc)
            self._refresh_storage_status()
            logger.warning(
                "SQLite incremental_vacuum failed trigger=%s error=%s", trigger, exc
            )
            return {
                "status": "failure",
                "trigger": trigger,
                "mode": "incremental",
                "error": str(exc),
                "at": self._status["last_vacuum_at"],
            }

    def _refresh_storage_status(self) -> None:
        db_path = self.config.db_path
        wal_path = f"{db_path}-wal"
        self._status["db_file_bytes"] = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        self._status["wal_file_bytes"] = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        self._status["current_db_size"] = int(self._status["db_file_bytes"]) + int(self._status["wal_file_bytes"])
        self._status["max_db_size"] = self.config.db_max_bytes
        usage = shutil.disk_usage(os.path.dirname(db_path) or ".")
        self._status["free_disk_bytes"] = usage.free
        self._status["db_max_bytes"] = self.config.db_max_bytes
        self._status["wal_max_bytes"] = self.config.wal_max_bytes
        self._status["data_retention_mode"] = "bounded_hot_cache"
        self._status["hot_cache_retention_hours"] = self.config.rotation_retention_hours
        self._status["archive_enabled"] = False
        self._status["warning_threshold"] = self.config.storage_warning_threshold
        self._status["critical_threshold"] = self.config.storage_critical_threshold
        self._status["emergency_threshold"] = self.config.storage_emergency_threshold
        if not self._status.get("storage_degraded"):
            self._status["storage_mode"] = self._storage_mode()
        self._status["free_disk_warning_bytes"] = self.config.free_disk_warning_bytes
        self._status["free_disk_critical_bytes"] = self.config.free_disk_critical_bytes
        if self._conn is not None:
            page_size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
            freelist_pages = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0])
            self._status["sqlite_page_size"] = page_size
            self._status["sqlite_freelist_pages"] = freelist_pages
            self._status["sqlite_reclaimable_bytes"] = page_size * freelist_pages
        self._status["adaptive_retention_min_hours"] = self.config.adaptive_retention_min_hours
        self._status["adaptive_retention_max_batches"] = self.config.adaptive_retention_max_batches
        self._status["size_cleanup_target_bytes"] = self._size_cleanup_target_bytes()
        self._status["write_guard_active"] = self._storage_mode() == "emergency" or bool(self._status.get("storage_degraded"))
        self._status["storage_status"], self._status["storage_reasons"] = self._evaluate_storage_status()

    def _evaluate_storage_status(self) -> tuple[str, list[str]]:
        reasons: list[str] = []
        status = "ok"

        free_disk_bytes = int(self._status.get("free_disk_bytes") or 0)
        current_size = int(self._status.get("current_db_size") or 0)
        db_file_bytes = int(self._status.get("db_file_bytes") or 0)
        wal_file_bytes = int(self._status.get("wal_file_bytes") or 0)
        storage_mode = str(self._status.get("storage_mode") or "normal")

        if not self._status.get("healthy", False):
            status = "critical"
            reasons.append("persistence unhealthy")

        if self._status.get("storage_degraded"):
            status = "critical"
            reasons.append("storage degraded after rotation failure")

        if free_disk_bytes <= self.config.free_disk_critical_bytes:
            status = "critical"
            reasons.append("free disk below critical threshold")
        elif free_disk_bytes <= self.config.free_disk_warning_bytes and status != "critical":
            status = "warning"
            reasons.append("free disk below warning threshold")

        if storage_mode in {"warning", "critical", "emergency"}:
            reasons.append(f"storage mode {storage_mode}")
            if storage_mode == "warning" and status == "ok":
                status = "warning"
            elif storage_mode in {"critical", "emergency"}:
                status = "warning"

        if current_size > self.config.db_max_bytes:
            reasons.append("database file exceeds configured max")
            if status == "ok":
                status = "warning"

        if wal_file_bytes > self.config.wal_max_bytes:
            reasons.append("wal file exceeds configured max")
            if status == "ok":
                status = "warning"

        if self._status.get("cleanup_status") == "failure":
            status = "critical"
            reasons.append("cleanup failed")

        if self._status.get("last_checkpoint_status") == "failure":
            status = "critical"
            reasons.append("checkpoint failed")

        return status, reasons


def _first_or_none(values: Optional[Iterable[str]]) -> Optional[str]:
    if not values:
        return None
    for value in values:
        return value
    return None


def _parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
