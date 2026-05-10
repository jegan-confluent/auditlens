import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

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
FORWARDER_HEALTH_TIMEOUT_SECONDS = 0.5


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

    def reset(self) -> None:
        with self._lock:
            self._last_fetch_monotonic = None
            self._snapshot = None

    def get(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            cached = self._snapshot
            last_fetch = self._last_fetch_monotonic
            if cached is not None and last_fetch is not None and (now - last_fetch) < self._ttl:
                return cached
        # Cache miss or expired — fetch with a tight timeout.
        snapshot = self._fetch_now()
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

    def reset(self) -> None:
        with self._lock:
            self._snapshots.clear()

    def get(self, db: Session) -> datetime | None:
        bind = db.get_bind()
        key = id(bind)
        now = time.monotonic()
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is not None and (now - snapshot[0]) < self._ttl:
                return snapshot[1]
        latest = self._fetch_now(db)
        with self._lock:
            self._snapshots[key] = (time.monotonic(), latest)
        return latest

    @staticmethod
    def _fetch_now(db: Session) -> datetime | None:
        """Run MAX(timestamp) with a tight statement_timeout. Any failure
        returns None; the route never 500s on this lookup.

        Uses the ORM column reference (not raw SQL) so SQLAlchemy
        type-decodes the SQLite string column back to a Python datetime
        — raw `text()` returns strings on SQLite.
        """
        # Local import keeps the system_service module importable in test
        # contexts that don't load the full ORM (e.g. classifier-only tests).
        from sqlalchemy import func, select

        from backend.app.db.models import AuditEvent

        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text(f"SET LOCAL statement_timeout = {DB_LATEST_EVENT_TIMEOUT_MS}"))
            result = db.execute(select(func.max(AuditEvent.timestamp))).scalar_one_or_none()
        except (OperationalError, SQLAlchemyError) as exc:
            db.rollback()
            logger.warning(
                "/system/status MAX(timestamp) failed: %s",
                exc.__class__.__name__,
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
        # Some dialects/drivers return ISO strings even through the ORM.
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
    return status
