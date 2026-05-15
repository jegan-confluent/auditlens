"""Filter dropdown options.

Three production-shaped concerns are addressed here:

* Result sets are capped at the top 500 most frequent values per column. The
  endpoint returns dropdown choices; sending a 100k-item list to the browser
  is wasteful and rarely useful.
* The whole result is wrapped in a 60-second TTL cache keyed by the underlying
  engine, so dashboard repaints do not hammer the DB for distinct queries.
* On Postgres each per-column query is wrapped with a short
  ``statement_timeout`` and JIT disabled, and aggregates over the most recent
  ``FILTER_OPTIONS_RECENT_SAMPLE`` rows rather than the entire table. At 10M+
  rows a full-table ``GROUP BY`` runs into the 30s route-level timeout; the
  recent-sample strategy keeps the dropdown populated with the values users
  actually filter on while bounding the scan size. Cancelled queries fall back
  to an empty list so the endpoint never 500s on a slow column.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any

from cachetools import TTLCache
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from src.product.event_normalization import canonical_resource_type


FILTER_OPTIONS_LIMIT = 500
FILTER_OPTIONS_TTL_SECONDS = 60
# Per-statement timeout (Postgres-only). The route is non-critical (dropdown
# population). 8 s is the budget the user-facing fetch can absorb; anything
# longer ends up looking like an outage.
FILTER_OPTIONS_STATEMENT_TIMEOUT_MS = 8000
# Recent-sample size for the Postgres path. Aggregating over the most recent
# N rows by timestamp gives a representative dropdown without scanning the
# full table. 50000 keeps total per-column wall-clock under ~1 s warm.
FILTER_OPTIONS_RECENT_SAMPLE = 50000

logger = logging.getLogger("auditlens.backend.filter_options")

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


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _apply_postgres_query_guards(db: Session) -> None:
    """Best-effort per-statement guards on Postgres.

    SET LOCAL is scoped to the current transaction and reverts on commit. JIT
    compilation alone adds ~2-4 s to these aggregations on a cold plan — pure
    overhead for a dropdown query.
    """
    db.execute(text(f"SET LOCAL statement_timeout = {FILTER_OPTIONS_STATEMENT_TIMEOUT_MS}"))
    db.execute(text("SET LOCAL jit = off"))


def _distinct_top_n_sqlite(db: Session, column, *, limit: int = FILTER_OPTIONS_LIMIT) -> list[str]:
    """Return the top ``limit`` most-frequent values for ``column`` (SQLite)."""
    rows = db.execute(
        select(column, func.count(AuditEvent.id).label("freq"))
        .where(column.isnot(None))
        .where(column != "")
        .group_by(column)
        .order_by(func.count(AuditEvent.id).desc(), column.asc())
        .limit(limit)
    ).all()
    return [str(value) for value, _freq in rows if value not in (None, "")]


def _distinct_top_n_postgres(
    db: Session,
    column,
    *,
    limit: int = FILTER_OPTIONS_LIMIT,
    sample: int = FILTER_OPTIONS_RECENT_SAMPLE,
) -> list[str]:
    """Top values from the most recent ``sample`` rows (Postgres path)."""
    sub = (
        select(column.label("value"))
        .where(column.isnot(None))
        .where(column != "")
        .order_by(AuditEvent.timestamp.desc())
        .limit(sample)
        .subquery()
    )
    stmt = (
        select(sub.c.value, func.count().label("freq"))
        .group_by(sub.c.value)
        .order_by(func.count().desc(), sub.c.value.asc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [str(value) for value, _freq in rows if value not in (None, "")]


def _safe_top_n(db: Session, column, *, label: str) -> list[str]:
    """Run the per-column dropdown query with timeout and graceful fallback."""
    _record_db_call(label)
    if not _is_postgres(db):
        return _distinct_top_n_sqlite(db, column)
    try:
        _apply_postgres_query_guards(db)
        return _distinct_top_n_postgres(db, column)
    except OperationalError as exc:
        # statement_timeout fires as QueryCanceled (sqlstate 57014). We don't
        # want a slow dropdown column to 500 the whole endpoint — an empty
        # list keeps the page rendering and the user can still type into the
        # filter input.
        db.rollback()
        logger.warning(
            "filter_options: dropdown query for %s timed out or failed (%s); returning empty list",
            label,
            exc.__class__.__name__,
        )
        return []


def _distinct_resource_types(db: Session) -> list[str]:
    rows = _safe_top_n(db, AuditEvent.resource_type, label="resource_types")
    values = {canonical_resource_type(value) for value in rows}
    return sorted(values)


def _build_filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "resource_types": _distinct_resource_types(db),
        "action_categories": _safe_top_n(db, AuditEvent.action_category, label="action_category"),
        "results": _safe_top_n(db, AuditEvent.result, label="result"),
        "actors": _safe_top_n(db, AuditEvent.actor, label="actor"),
        # AuditEvent.environment_name is a hybrid property layered over the
        # _environment_name column; we go through the column directly so the
        # GROUP BY pushes down rather than triggering Python-side resolution.
        "environments": _safe_top_n(db, AuditEvent._environment_name, label="environment_name"),
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


# ---------------------------------------------------------------------------
# Hierarchy endpoint — Service → Category → Method, 5-minute cache
# ---------------------------------------------------------------------------

HIERARCHY_TTL_SECONDS = 300
HIERARCHY_MAX_DISTINCT_ROWS = 5000

_SERVICE_LABELS: dict[str, str] = {
    "kafka": "Kafka",
    "schema-registry": "Schema Registry",
    "flink": "Flink",
    "ksql": "ksQL",
    "tableflow": "Tableflow",
    "mds": "MDS",
    "io.confluent": "Confluent Cloud",
    "auth": "Authentication",
}

_hierarchy_cache: TTLCache[int, dict[str, Any]] = TTLCache(maxsize=8, ttl=HIERARCHY_TTL_SECONDS)
_hierarchy_cache_lock = threading.Lock()


def _derive_service_key(action: str) -> str:
    """Map an action method name to a top-level service key."""
    lower = action.lower()
    # Match known data-plane prefixes first (kafka., schema-registry., etc.)
    for prefix in ("kafka.", "schema-registry.", "flink.", "ksql.", "tableflow.", "mds."):
        if lower.startswith(prefix):
            return prefix.rstrip(".")
    if lower.startswith("io.confluent."):
        return "io.confluent"
    if "." not in action:
        return "auth"
    return action.split(".")[0].lower()


def _build_filter_hierarchy(db: Session) -> dict[str, Any]:
    """Build 3-level Service → Category → Method tree from live audit_events."""
    stmt = (
        select(AuditEvent.action, AuditEvent.action_category)
        .where(AuditEvent.action.isnot(None))
        .where(AuditEvent.action != "")
        .distinct()
        .limit(HIERARCHY_MAX_DISTINCT_ROWS)
    )
    rows = db.execute(stmt).all()

    tree: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for action, category in rows:
        if not action:
            continue
        service_key = _derive_service_key(action)
        cat = (category or "Other").strip() or "Other"
        tree[service_key][cat].append(action)

    services = []
    for service_key in sorted(tree.keys()):
        categories = []
        for cat_name in sorted(tree[service_key].keys()):
            methods = sorted(tree[service_key][cat_name])
            label_prefix = service_key.rstrip(".") + "."
            categories.append({
                "name": cat_name,
                "methods": [
                    {
                        "action": m,
                        "label": m[len(label_prefix):] if m.lower().startswith(label_prefix.lower()) else m,
                    }
                    for m in methods
                ],
            })
        services.append({
            "name": service_key,
            "label": _SERVICE_LABELS.get(service_key, service_key.replace("-", " ").title()),
            "categories": categories,
        })

    return {"services": services}


def get_filter_hierarchy(db: Session) -> dict[str, Any]:
    bind = db.get_bind()
    cache_key = id(bind)
    with _hierarchy_cache_lock:
        cached = _hierarchy_cache.get(cache_key)
    if cached is not None:
        return cached
    result = _build_filter_hierarchy(db)
    with _hierarchy_cache_lock:
        _hierarchy_cache[cache_key] = result
    return result


def clear_filter_hierarchy_cache() -> None:
    """Drop the hierarchy cache. Call from tests after mutating data."""
    with _hierarchy_cache_lock:
        _hierarchy_cache.clear()
