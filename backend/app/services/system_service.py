import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health_session

logger = logging.getLogger("auditlens.backend.system")


# How long to trust a cached forwarder health snapshot before re-fetching.
# Short enough to track real outages quickly; long enough that bursty
# /ready probes from a kubelet do not stampede the forwarder.
FORWARDER_HEALTH_TTL_SECONDS = 5.0
FORWARDER_HEALTH_TIMEOUT_SECONDS = 10.0


def _unknown_status(reason: str) -> dict[str, Any]:
    return {
        "consumer_state": "unknown",
        "last_successful_poll": None,
        "retry_count": 0,
        "consecutive_error_count": 0,
        "last_error": reason,
        "consumer_lag": None,
        "records_consumed_total": 0,
        "db_writer_enabled": False,
        "db_writer_state": "unknown",
        "db_write_success_total": 0,
        "db_write_error_total": 0,
        "db_write_batch_size": 0,
        "db_last_successful_write": None,
        "db_last_error": reason,
        "db_last_cleanup_at": None,
        "db_last_cleanup_deleted_count": 0,
    }


def _shape_forwarder_payload(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = payload.get("observability", {}).get("consumer_runtime", {})
    db_writer = payload.get("observability", {}).get("db_writer", {})
    return {
        "consumer_state": runtime.get("consumer_state") or payload.get("components", [{}])[0].get("status", "unknown"),
        "last_successful_poll": runtime.get("last_successful_poll"),
        "retry_count": int(runtime.get("retry_count") or 0),
        "consecutive_error_count": int(runtime.get("consecutive_error_count") or 0),
        "last_error": runtime.get("last_error"),
        "consumer_lag": payload.get("consumer_lag"),
        "records_consumed_total": int(runtime.get("records_consumed_total") or 0),
        "db_writer_enabled": bool(db_writer.get("enabled", False)),
        "db_writer_state": db_writer.get("db_writer_state", "unknown"),
        "db_write_success_total": int(db_writer.get("db_write_success_total") or 0),
        "db_write_error_total": int(db_writer.get("db_write_error_total") or 0),
        "db_write_batch_size": int(db_writer.get("db_write_batch_size") or 0),
        "db_last_successful_write": db_writer.get("db_last_successful_write"),
        "db_last_error": db_writer.get("db_last_error"),
        "db_last_cleanup_at": db_writer.get("db_last_cleanup_at"),
        "db_last_cleanup_deleted_count": int(db_writer.get("db_last_cleanup_deleted_count") or 0),
    }


class _ForwarderHealthCache:
    """Caches the most-recent forwarder /health snapshot.

    The /ready probe used to do a synchronous httpx GET on every call, which
    blocked the event loop for up to 2 s and caused readiness flapping when
    the forwarder was slow to respond. We now memoize the snapshot for
    ``FORWARDER_HEALTH_TTL_SECONDS``; calls within the TTL return in
    sub-millisecond time without touching the network.
    """

    def __init__(self, ttl_seconds: float = FORWARDER_HEALTH_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._last_fetch_monotonic: float | None = None
        self._snapshot: dict[str, Any] | None = None
        self._fetching: bool = False

    def reset(self) -> None:
        with self._lock:
            self._last_fetch_monotonic = None
            self._snapshot = None
            self._fetching = False

    def get(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            cached = self._snapshot
            last_fetch = self._last_fetch_monotonic
            if cached is not None and last_fetch is not None and (now - last_fetch) < self._ttl:
                return cached
            # Prevent thundering herd: if another thread is already fetching,
            # return stale snapshot (or empty dict) rather than pile-on.
            if self._fetching:
                return cached if cached is not None else _unknown_status("fetching")
            self._fetching = True
        try:
            snapshot = self._fetch_now()
        finally:
            with self._lock:
                self._fetching = False
        with self._lock:
            self._snapshot = snapshot
            self._last_fetch_monotonic = time.monotonic()
        return snapshot

    def prime(self, snapshot: dict[str, Any]) -> None:
        """Seed the cache with a known snapshot. Used by tests + the
        startup event hook to avoid a cold fetch on the first request."""
        with self._lock:
            self._snapshot = snapshot
            self._last_fetch_monotonic = time.monotonic()

    def _fetch_now(self) -> dict[str, Any]:
        settings = get_settings()
        try:
            response = httpx.get(settings.forwarder_health_url, timeout=FORWARDER_HEALTH_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return _unknown_status(str(exc))
        return _shape_forwarder_payload(payload)


_forwarder_health_cache = _ForwarderHealthCache()


def reset_forwarder_health_cache() -> None:
    """Drop the in-process cache. Safe for tests + admin tooling."""
    _forwarder_health_cache.reset()


# ────────────────────────── DB latest-event cache ──────────────────────
# `MAX(timestamp) FROM audit_events` is index-eligible
# (idx_audit_events_timestamp_desc) but at high write rate it still
# costs a few ms — and /system/status gets polled every 30 s by the
# frontend banner. Cache for 10 s so the route stays fast and the DB
# isn't repeatedly probed.
DB_LATEST_EVENT_TTL_SECONDS = 10.0
DB_LATEST_EVENT_TIMEOUT_MS = 3_000


class _DbLatestEventCache:
    """Caches `MAX(timestamp) FROM audit_events` per engine."""

    def __init__(self, ttl_seconds: float = DB_LATEST_EVENT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # value is (datetime | None) — None means "query attempted but no
        # rows / failed" so the next request stays cached for the TTL.
        self._snapshots: dict[int, tuple[float, datetime | None]] = {}
        self._fetching: set[int] = set()

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()
            self._fetching.clear()

    def get(self, db: Session) -> datetime | None:
        bind = db.get_bind()
        key = id(bind)
        now = time.monotonic()
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is not None and (now - snapshot[0]) < self._ttl:
                return snapshot[1]
            # Prevent thundering herd: return stale value if another thread is fetching.
            if key in self._fetching:
                return snapshot[1] if snapshot is not None else None
            self._fetching.add(key)
        try:
            latest = self._fetch_now(db)
        finally:
            with self._lock:
                self._fetching.discard(key)
        with self._lock:
            self._snapshots[key] = (time.monotonic(), latest)
        return latest

    @staticmethod
    def _fetch_now(db: Session) -> datetime | None:
        """Run MAX(timestamp) across both audit tables. Any failure returns
        None; the route never 500s on this lookup.

        The UNION ALL covers audit_events_noise so the status strip
        reflects noise-lane writes — otherwise a forwarder that is
        actively writing noise-only traffic shows a stale timestamp.
        """
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text(f"SET LOCAL statement_timeout = {DB_LATEST_EVENT_TIMEOUT_MS}"))
            result = db.execute(text(
                "SELECT MAX(ts) FROM ("
                "  SELECT MAX(timestamp) AS ts FROM audit_events"
                "  UNION ALL"
                "  SELECT MAX(timestamp) AS ts FROM audit_events_noise"
                ") _latest_combined"
            )).scalar_one_or_none()
        except (OperationalError, SQLAlchemyError):
            # audit_events_noise may not exist in older deployments (pre-migration 0007).
            # Fall back to audit_events only rather than returning stale None.
            db.rollback()
            try:
                from sqlalchemy import func, select
                from backend.app.db.models import AuditEvent
                result = db.execute(select(func.max(AuditEvent.timestamp))).scalar_one_or_none()
            except Exception as exc2:
                logger.warning(
                    "/system/status MAX(timestamp) failed (both tables): %s",
                    exc2.__class__.__name__,
                )
                return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("/system/status MAX(timestamp) unexpected error: %s", exc)
            return None
        if result is None:
            return None
        if isinstance(result, datetime):
            if result.tzinfo is None:
                return result.replace(tzinfo=timezone.utc)
            return result.astimezone(timezone.utc)
        # text() returns ISO strings on SQLite — parse them back.
        if isinstance(result, str):
            try:
                parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                return None
        return None


_db_latest_event_cache = _DbLatestEventCache()


def reset_db_latest_event_cache() -> None:
    """Drop the cached MAX(timestamp). Used by tests + admin tooling."""
    _db_latest_event_cache.reset()


# ────────────────────────────── pipeline lag ───────────────────────────
def _classify_pipeline_status(
    *,
    db_behind_seconds: int | None,
    consumer_lag: int | None,
    db_latest_event_at: datetime | None,
) -> str:
    """healthy < 60s & < 100k lag; stalled > 300s OR > 1M OR unknown DB
    timestamp; degraded otherwise."""
    if db_latest_event_at is None:
        return "stalled"
    if db_behind_seconds is None:
        return "stalled"
    if db_behind_seconds > 300 or (consumer_lag is not None and consumer_lag > 1_000_000):
        return "stalled"
    if (
        db_behind_seconds < 60
        and (consumer_lag is None or consumer_lag < 100_000)
    ):
        return "healthy"
    return "degraded"


def _to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_pipeline_lag(db: Session) -> dict[str, Any]:
    """Assemble the /system/status pipeline_lag block.

    Reads the 5-second-cached forwarder /health snapshot and the 10-second-
    cached DB MAX(timestamp). On forwarder unreachable the consumer-side
    fields are None and the status falls to "unknown" (per spec).
    """
    forwarder = _forwarder_health_cache.get()
    forwarder_unreachable = bool(
        forwarder.get("last_error")
        and forwarder.get("consumer_state") == "unknown"
    )
    consumer_lag = forwarder.get("consumer_lag")
    forwarder_last_write_at = forwarder.get("db_last_successful_write")

    db_latest = _db_latest_event_cache.get(db)
    db_behind_seconds: int | None = None
    if db_latest is not None:
        delta = (datetime.now(timezone.utc) - db_latest).total_seconds()
        db_behind_seconds = int(max(0, delta))

    if forwarder_unreachable:
        status = "unknown"
    else:
        status = _classify_pipeline_status(
            db_behind_seconds=db_behind_seconds,
            consumer_lag=consumer_lag if isinstance(consumer_lag, int) else None,
            db_latest_event_at=db_latest,
        )

    replay_recommended = (
        consumer_lag == 0
        and db_behind_seconds is not None
        and db_behind_seconds > 300
    )

    return {
        "kafka_consumer_lag_messages": consumer_lag if isinstance(consumer_lag, int) else None,
        "db_latest_event_at": _to_iso_z(db_latest),
        "forwarder_last_write_at": forwarder_last_write_at,
        "db_behind_seconds": db_behind_seconds,
        "replay_recommended": bool(replay_recommended),
        "status": status,
    }


def get_storage_usage(db: Session) -> dict[str, Any]:
    settings = get_settings()
    if settings.database_mode == "sqlite":
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path == ":memory:":
            return {"mode": "sqlite", "path": ":memory:", "bytes": 0}
        size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        wal_path = f"{db_path}-wal"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        return {"mode": "sqlite", "path": db_path, "bytes": size + wal_size, "db_bytes": size, "wal_bytes": wal_size}
    size = db.scalar(text("select pg_database_size(current_database())"))
    return {"mode": "postgres", "bytes": int(size or 0)}


# ─────────────────────── Postgres storage health ───────────────────────────
_STORAGE_HEALTH_TTL_SECONDS = 60.0
_STORAGE_HEALTH_TIMEOUT_MS = 3_000


class _StorageHealthCache:
    """Caches the storage health block for 60 seconds."""

    def __init__(self, ttl_seconds: float = _STORAGE_HEALTH_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._snapshots: dict[int, tuple[float, dict[str, Any]]] = {}

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()

    def get(self, db: Session) -> dict[str, Any]:
        bind = db.get_bind()
        key = id(bind)
        now = time.monotonic()
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is not None and (now - snapshot[0]) < self._ttl:
                return snapshot[1]
        result = self._fetch_now(db)
        with self._lock:
            self._snapshots[key] = (time.monotonic(), result)
        return result

    @staticmethod
    def _fetch_now(db: Session) -> dict[str, Any]:
        settings = get_settings()
        dialect = db.get_bind().dialect.name
        if dialect != "postgresql":
            return {
                "status": "healthy",
                "db_size_bytes": 0,
                "db_size_pretty": "n/a (sqlite)",
                "audit_events_size_pretty": "n/a",
                "noise_table_size_pretty": "n/a",
                "oldest_event_at": None,
                "newest_event_at": None,
                "events_with_raw_payload": 0,
                "retention_days": settings.event_retention_days,
            }
        try:
            db.execute(text(f"SET LOCAL statement_timeout = {_STORAGE_HEALTH_TIMEOUT_MS}"))
            db_size = db.scalar(text("SELECT pg_database_size(current_database())")) or 0
            audit_size = db.scalar(text("SELECT pg_total_relation_size('audit_events')")) or 0
            noise_size_result: Optional[int] = None
            try:
                noise_size_result = db.scalar(text("SELECT pg_total_relation_size('audit_events_noise')"))
            except Exception:
                pass
            oldest_at = db.scalar(text("SELECT MIN(timestamp) FROM audit_events"))
            newest_at = db.scalar(text("SELECT MAX(timestamp) FROM audit_events"))
            raw_count = db.scalar(text(
                "SELECT COUNT(*) FROM audit_events WHERE raw_payload_json IS NOT NULL AND raw_payload_json != '{}'"
            )) or 0
        except Exception as exc:
            logger.warning("storage_health query failed: %s", exc)
            db.rollback()
            return {"status": "error", "error": str(exc), "retention_days": settings.event_retention_days}

        def pretty_bytes(n: int) -> str:
            if n < 1024:
                return f"{n} B"
            if n < 1024 ** 2:
                return f"{n / 1024:.1f} KB"
            if n < 1024 ** 3:
                return f"{n / 1024 ** 2:.1f} MB"
            return f"{n / 1024 ** 3:.2f} GB"

        gb = db_size / (1024 ** 3)
        if gb >= 40:
            status = "critical"
        elif gb >= 20:
            status = "warning"
        else:
            status = "healthy"

        def _iso(ts: Any) -> Optional[str]:
            if ts is None:
                return None
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return str(ts)

        return {
            "status": status,
            "db_size_bytes": int(db_size),
            "db_size_pretty": pretty_bytes(int(db_size)),
            "audit_events_size_pretty": pretty_bytes(int(audit_size)),
            "noise_table_size_pretty": pretty_bytes(int(noise_size_result or 0)),
            "oldest_event_at": _iso(oldest_at),
            "newest_event_at": _iso(newest_at),
            "events_with_raw_payload": int(raw_count),
            "retention_days": settings.event_retention_days,
        }


_storage_health_cache = _StorageHealthCache()


def reset_storage_health_cache() -> None:
    _storage_health_cache.reset()


def get_storage_health(db: Session) -> dict[str, Any]:
    return _storage_health_cache.get(db)


def get_forwarder_status() -> dict[str, Any]:
    """Return the most-recent forwarder /health snapshot.

    This is the cached path used by the readiness probe. Calls within
    ``FORWARDER_HEALTH_TTL_SECONDS`` of the previous fetch return without
    issuing a new HTTP request; that keeps Kubernetes liveness/readiness
    probes sub-millisecond even when the upstream forwarder is slow.
    """
    return _forwarder_health_cache.get()


def get_system_status(db: Session) -> dict[str, Any]:
    status = get_forwarder_status()
    status["database_mode"] = get_settings().database_mode
    try:
        status["storage_usage"] = get_storage_usage(db)
    except Exception as exc:
        status["storage_usage"] = {"mode": status["database_mode"], "error": str(exc)}
    try:
        status["db_health"] = check_db_health_session(db)
    except Exception as exc:
        status["db_health"] = {"can_connect": False, "can_query": False, "error": str(exc)}
    # Pipeline lag is best-effort — wrapped so a transient DB hiccup
    # can never 500 the status route. Falls back to status="unknown".
    try:
        pipeline = get_pipeline_lag(db)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("pipeline_lag assembly failed: %s", exc)
        pipeline = {
            "kafka_consumer_lag_messages": None,
            "db_latest_event_at": None,
            "forwarder_last_write_at": None,
            "db_behind_seconds": None,
            "replay_recommended": False,
            "status": "unknown",
        }
    status["pipeline_lag"] = pipeline
    status["pipeline_status"] = pipeline.get("status", "unknown")
    try:
        status["storage_health"] = get_storage_health(db)
    except Exception as exc:
        status["storage_health"] = {"status": "error", "error": str(exc)}
    try:
        from backend.app.services.cold_storage_service import get_cold_storage_status
        status["cold_storage"] = get_cold_storage_status(db)
    except Exception as exc:
        status["cold_storage"] = {"enabled": False, "status": "error", "error": str(exc)}
    _s = get_settings()
    status["auth_enabled"] = _s.api_auth_enabled
    _cf_key = _s.confluent_cloud_api_key or _s.confluent_api_key
    _cf_secret = _s.confluent_cloud_api_secret or _s.confluent_api_secret
    status["confluent_configured"] = bool(_cf_key and _cf_secret)
    return status
