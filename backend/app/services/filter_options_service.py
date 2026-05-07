"""Filter dropdown options.

Two production-shaped concerns are addressed here:

* Result sets are capped at the top 500 most frequent values per column. The
  endpoint returns dropdown choices; sending a 100k-item list to the browser
  is wasteful and rarely useful.
* The whole result is wrapped in a 60-second TTL cache keyed by the underlying
  engine, so dashboard repaints do not hammer the DB for distinct queries.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from cachetools import TTLCache
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from src.product.event_normalization import canonical_resource_type


FILTER_OPTIONS_LIMIT = 500
FILTER_OPTIONS_TTL_SECONDS = 60

# Module-level cache. Keyed by the engine identity so two tests using two
# different engines never share a cache entry. ``TTLCache`` plus an explicit
# lock is enough — cache pressure is tiny (a handful of API replicas).
_options_cache: TTLCache[int, dict[str, list[str]]] = TTLCache(maxsize=8, ttl=FILTER_OPTIONS_TTL_SECONDS)
_options_cache_lock = threading.Lock()
_db_call_counter: dict[str, int] = {}  # exposed for tests


def _record_db_call(label: str) -> None:
    _db_call_counter[label] = _db_call_counter.get(label, 0) + 1


def reset_db_call_counter() -> None:
    _db_call_counter.clear()


def clear_filter_options_cache() -> None:
    """Drop the in-process cache. Call from tests after mutating data."""
    with _options_cache_lock:
        _options_cache.clear()


def _distinct_top_n(db: Session, column, *, limit: int = FILTER_OPTIONS_LIMIT) -> list[str]:
    """Return the top ``limit`` most-frequent values for ``column`` (descending)."""
    _record_db_call(getattr(column, "key", "unknown"))
    rows = db.execute(
        select(column, func.count(AuditEvent.id).label("freq"))
        .where(column.isnot(None))
        .where(column != "")
        .group_by(column)
        .order_by(func.count(AuditEvent.id).desc(), column.asc())
        .limit(limit)
    ).all()
    return [str(value) for value, _freq in rows if value not in (None, "")]


def _distinct_resource_types(db: Session) -> list[str]:
    _record_db_call("resource_types")
    rows = db.execute(
        select(AuditEvent.resource_type, func.count(AuditEvent.id).label("freq"))
        .where(AuditEvent.resource_type.isnot(None))
        .where(AuditEvent.resource_type != "")
        .group_by(AuditEvent.resource_type)
        .order_by(func.count(AuditEvent.id).desc(), AuditEvent.resource_type.asc())
        .limit(FILTER_OPTIONS_LIMIT)
    ).all()
    values = {canonical_resource_type(value) for value, _freq in rows if value not in (None, "")}
    expected = {"topic", "subject", "connector", "role_binding", "environment"}
    return sorted(values | expected)


def _build_filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "resource_types": _distinct_resource_types(db),
        "action_categories": _distinct_top_n(db, AuditEvent.action_category),
        "results": _distinct_top_n(db, AuditEvent.result),
        "actors": _distinct_top_n(db, AuditEvent.actor),
    }


def get_filter_options(db: Session) -> dict[str, list[str]]:
    bind = db.get_bind()
    cache_key = id(bind)
    with _options_cache_lock:
        cached = _options_cache.get(cache_key)
    if cached is not None:
        return cached
    result = _build_filter_options(db)
    with _options_cache_lock:
        _options_cache[cache_key] = result
    return result


# Re-export for tests.
def _internal_state() -> dict[str, Any]:  # pragma: no cover - debug helper
    return {
        "cache_size": len(_options_cache),
        "db_calls": dict(_db_call_counter),
        "ttl": FILTER_OPTIONS_TTL_SECONDS,
        "now": time.monotonic(),
    }
