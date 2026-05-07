import os
import threading
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health_session


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
    return status
