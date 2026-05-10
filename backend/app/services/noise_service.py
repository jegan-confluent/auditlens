"""Service-layer helpers for the audit_events_noise table.

The noise table holds bulk-noise rows the forwarder writes via the
short-circuit lane — every routine `mds.Authorize`, `kafka.Fetch`,
`kafka.Produce` and friends. Three customer-visible API surfaces read
from it:

  - GET /summary/methods — unified method distribution (signal + noise)
  - GET /summary?include_noise=true — top noise methods alongside the
    existing decision-mode summary
  - GET /events?show_noise=true — paginated noise rows for ad-hoc query

The table may not exist (e.g. an older deployment that pre-dates
migration 0007). Every helper here MUST treat that as "no data" rather
than 500-ing the route. We probe once on engine attach and cache the
existence answer so the inner loops never pay for repeated information_schema
lookups.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cachetools import TTLCache
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger("auditlens.backend.noise")


# ──────────────────────── lightweight Table handle ─────────────────────
# We can't import db_writer.audit_events_noise from here without dragging
# in the full forwarder import path, and the backend already declares
# ResourceCatalog / AuditEvent on a separate Base. So redeclare a minimal
# Core Table that mirrors migration 0007 — read-only access is all we need.
_metadata = MetaData()
audit_events_noise = Table(
    "audit_events_noise",
    _metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("actor", String(255), nullable=True),
    Column("action", String(255), nullable=True),
    Column("result", String(32), nullable=True),
    Column("resource_name", String(512), nullable=True),
    Column("source_ip", String(128), nullable=True),
    Column("environment_id", String(255), nullable=True),
    Column("cluster_id", String(255), nullable=True),
    Column("is_denied", Boolean, nullable=False, default=False),
    Column("ingested_at", DateTime(timezone=True), nullable=True),
)


# ──────────────────────────── per-engine flags ─────────────────────────
_existence_cache: dict[int, bool] = {}
_existence_lock = threading.Lock()


def reset_noise_table_existence_cache() -> None:
    """Drop the cached `does the noise table exist?` answer. Used by tests
    that flip the schema between assertions and by admin tooling."""
    with _existence_lock:
        _existence_cache.clear()


def noise_table_exists(db: Session) -> bool:
    """Cached existence probe. False if the table is absent OR the probe
    itself raises (best-effort — never propagate)."""
    bind = db.get_bind()
    key = id(bind)
    with _existence_lock:
        cached = _existence_cache.get(key)
    if cached is not None:
        return cached
    try:
        present = "audit_events_noise" in set(inspect(bind).get_table_names())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("noise table existence probe failed: %s", exc)
        present = False
    with _existence_lock:
        _existence_cache[key] = present
    return present


# ───────────────────────────── time window ─────────────────────────────
TIME_WINDOW_MAX_HOURS = 24 * 30  # 30 days; matches existing /events budget.


def parse_time_window(value: str | None) -> datetime | None:
    """Parse `12h` / `45m` style windows. Returns the cutoff datetime
    (UTC, tz-aware) or None when value is empty. Raises ValueError on a
    bad shape so the route can return 400."""
    if not value:
        return None
    text_value = value.strip().lower()
    if not text_value:
        return None
    if not text_value[0].isdigit() or text_value[-1] not in ("m", "h"):
        raise ValueError("time_window must use a positive minute or hour value such as 5m or 12h")
    amount_part = text_value[:-1]
    unit = text_value[-1]
    try:
        amount = int(amount_part)
    except ValueError as exc:
        raise ValueError("time_window amount must be an integer") from exc
    if amount <= 0:
        raise ValueError("time_window amount must be positive")
    delta = timedelta(hours=amount) if unit == "h" else timedelta(minutes=amount)
    if delta.total_seconds() > TIME_WINDOW_MAX_HOURS * 3600:
        raise ValueError(f"time_window must be <= {TIME_WINDOW_MAX_HOURS}h")
    return datetime.now(timezone.utc) - delta


# ──────────────────────────── statement timeouts ───────────────────────
SUMMARY_NOISE_TIMEOUT_MS = 5_000
METHODS_TIMEOUT_MS = 10_000
EVENTS_NOISE_TIMEOUT_MS = 15_000


def _apply_pg_timeout(db: Session, timeout_ms: int) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


# ─────────────────────────── /events?show_noise ────────────────────────
NOISE_EVENTS_MAX_LIMIT = 500

# Filters that are meaningful on audit_events but have no matching column
# on audit_events_noise. The route returns 400 if the client sends any.
UNSUPPORTED_NOISE_FILTERS: tuple[str, ...] = (
    "signal_type",
    "impact_type",
    "change_type",
    "mode",
    "resource_type",
    "resource",
    "is_denied",
    "result",
    "cluster_name",
    "environment_name",
    "action_category",
    "hide_noise",
)


@dataclass
class NoiseEventsResult:
    items: list[dict[str, Any]]
    total: int


def list_noise_events(
    db: Session,
    *,
    time_window: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> NoiseEventsResult:
    """Return a page of audit_events_noise rows.

    Empty result (`items=[], total=0`) when the table is absent so the
    /events route can degrade gracefully rather than 500.
    """
    limit = max(1, min(int(limit), NOISE_EVENTS_MAX_LIMIT))
    offset = max(0, int(offset))
    if not noise_table_exists(db):
        return NoiseEventsResult(items=[], total=0)

    since = parse_time_window(time_window)

    conditions: list[Any] = []
    if since is not None:
        conditions.append(audit_events_noise.c.timestamp >= since)
    if actor and actor.strip():
        conditions.append(func.lower(audit_events_noise.c.actor).like(f"%{actor.strip().lower()}%"))
    if action and action.strip():
        conditions.append(func.lower(audit_events_noise.c.action).like(f"%{action.strip().lower()}%"))

    _apply_pg_timeout(db, EVENTS_NOISE_TIMEOUT_MS)

    count_query = select(func.count()).select_from(audit_events_noise)
    item_query = select(audit_events_noise)
    if conditions:
        count_query = count_query.where(and_(*conditions))
        item_query = item_query.where(and_(*conditions))
    item_query = item_query.order_by(
        audit_events_noise.c.timestamp.desc(),
        audit_events_noise.c.id.desc(),
    ).limit(limit).offset(offset)

    try:
        total = int(db.execute(count_query).scalar_one() or 0)
        rows = db.execute(item_query).mappings().all()
    except (OperationalError, SQLAlchemyError) as exc:
        # Statement timeout or other DB-side failure. Return empty rather
        # than 500 — the noise table is best-effort.
        db.rollback()
        logger.warning("noise events query failed: %s", exc.__class__.__name__)
        return NoiseEventsResult(items=[], total=0)

    items = [dict(row) for row in rows]
    return NoiseEventsResult(items=items, total=total)


# ───────────────────────── /summary?include_noise ──────────────────────
NOISE_SUMMARY_TOP_N = 10


def get_noise_summary(db: Session, *, retention_days: int) -> dict[str, Any] | None:
    """Top-N noise methods with totals. Returns None when the table is
    absent or the query fails — the caller treats None as 'no data'."""
    if not noise_table_exists(db):
        return None
    _apply_pg_timeout(db, SUMMARY_NOISE_TIMEOUT_MS)

    total_query = select(func.count()).select_from(audit_events_noise)
    top_query = (
        select(
            audit_events_noise.c.action.label("action"),
            func.count().label("count"),
        )
        .where(audit_events_noise.c.action.isnot(None))
        .group_by(audit_events_noise.c.action)
        .order_by(func.count().desc())
        .limit(NOISE_SUMMARY_TOP_N)
    )
    try:
        total = int(db.execute(total_query).scalar_one() or 0)
        top_rows = db.execute(top_query).all()
    except (OperationalError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("noise summary query failed: %s", exc.__class__.__name__)
        return None

    return {
        "total_noise_events": total,
        "top_noise_methods": [
            {"action": str(row[0] or ""), "count": int(row[1] or 0)} for row in top_rows
        ],
        "noise_table_rows": total,
        "noise_retention_days": int(retention_days),
    }


# ─────────────────────────── /summary/methods ──────────────────────────
METHODS_TTL_SECONDS = 60
METHODS_LIMIT_PER_TABLE = 200
# Aggregate over the most-recent N audit_events rows on Postgres rather
# than the entire table. At production scale (10M+ rows) a full GROUP BY
# action exhausts the 10s statement_timeout and the route degrades to
# noise-only. 50_000 is the same window FILTER_OPTIONS_RECENT_SAMPLE uses
# in filter_options_service — wide enough that any method seen in the
# last few hours is represented; bounded enough that the scan stays
# under ~1 s warm.
METHODS_RECENT_SAMPLE = 50_000

_methods_cache: TTLCache[int, dict[str, Any]] = TTLCache(maxsize=8, ttl=METHODS_TTL_SECONDS)
_methods_cache_lock = threading.Lock()


def clear_method_distribution_cache() -> None:
    with _methods_cache_lock:
        _methods_cache.clear()


def _query_signal_methods(db: Session) -> list[dict[str, Any]]:
    from backend.app.db.models import AuditEvent

    _apply_pg_timeout(db, METHODS_TIMEOUT_MS)

    if _is_postgres(db):
        # Recent-sample subquery — mirror of filter_options_service. The
        # outer aggregation runs over the top-N rows by timestamp instead
        # of the entire table. ORDER BY timestamp DESC + LIMIT is index-
        # eligible (idx_audit_events_timestamp_desc) so the subquery
        # itself is constant-time relative to table size.
        sub = (
            select(
                AuditEvent.action.label("value"),
                AuditEvent._signal_type.label("st"),
                AuditEvent.timestamp.label("ts"),
            )
            .where(AuditEvent.action.isnot(None))
            .where(AuditEvent.action != "")
            .order_by(AuditEvent.timestamp.desc())
            .limit(METHODS_RECENT_SAMPLE)
            .subquery()
        )
        query = (
            select(
                sub.c.value.label("action"),
                func.count().label("count"),
                func.max(sub.c.st).label("signal_type"),
                func.max(sub.c.ts).label("last_seen"),
            )
            .group_by(sub.c.value)
            .order_by(func.count().desc())
            .limit(METHODS_LIMIT_PER_TABLE)
        )
    else:
        # SQLite (demo + tests) — small datasets, full-table GROUP BY
        # is cheap. Keeps existing test fixtures honest.
        query = (
            select(
                AuditEvent.action.label("action"),
                func.count().label("count"),
                func.max(AuditEvent._signal_type).label("signal_type"),
                func.max(AuditEvent.timestamp).label("last_seen"),
            )
            .where(AuditEvent.action.isnot(None))
            .where(AuditEvent.action != "")
            .group_by(AuditEvent.action)
            .order_by(func.count().desc())
            .limit(METHODS_LIMIT_PER_TABLE)
        )

    try:
        rows = db.execute(query).all()
    except (OperationalError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("/summary/methods signal query failed: %s", exc.__class__.__name__)
        return []
    return [
        {
            "action": str(row[0] or ""),
            "count": int(row[1] or 0),
            "signal_type": str(row[2] or "informational"),
            "last_seen": row[3],
            "table": "signal",
        }
        for row in rows
    ]


def _query_noise_methods(db: Session) -> list[dict[str, Any]]:
    if not noise_table_exists(db):
        return []
    _apply_pg_timeout(db, METHODS_TIMEOUT_MS)
    query = (
        select(
            audit_events_noise.c.action.label("action"),
            func.count().label("count"),
            func.max(audit_events_noise.c.timestamp).label("last_seen"),
        )
        .where(audit_events_noise.c.action.isnot(None))
        .where(audit_events_noise.c.action != "")
        .group_by(audit_events_noise.c.action)
        .order_by(func.count().desc())
        .limit(METHODS_LIMIT_PER_TABLE)
    )
    try:
        rows = db.execute(query).all()
    except (OperationalError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("/summary/methods noise query failed: %s", exc.__class__.__name__)
        return []
    return [
        {
            "action": str(row[0] or ""),
            "count": int(row[1] or 0),
            "signal_type": "noise",
            "last_seen": row[2],
            "table": "noise",
        }
        for row in rows
    ]


def _merge_method_rows(
    signal_rows: list[dict[str, Any]],
    noise_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine identical-action rows from both tables.

    When the same action appears in both, sum the counts. The merged row
    keeps the signal table's signal_type (noise rows are constants); the
    table label becomes `signal` to indicate the action is observed in
    enriched events. last_seen is the more recent of the two.
    """
    by_action: dict[str, dict[str, Any]] = {}
    for row in signal_rows:
        by_action[row["action"]] = dict(row)
    for row in noise_rows:
        existing = by_action.get(row["action"])
        if existing is None:
            by_action[row["action"]] = dict(row)
            continue
        existing["count"] = int(existing.get("count", 0)) + int(row.get("count", 0))
        # Prefer the signal-table classification — only the noise row is
        # forced to "noise". The signal row's classification wins.
        # Pick the more recent last_seen.
        ls_signal = existing.get("last_seen")
        ls_noise = row.get("last_seen")
        if ls_signal is None or (ls_noise is not None and ls_noise > ls_signal):
            existing["last_seen"] = ls_noise
        # Keep table='signal' since this action appears in both, signal
        # is the queryable home that has all the enrichment.
    merged = sorted(by_action.values(), key=lambda r: int(r.get("count", 0)), reverse=True)
    return merged


def get_method_distribution(db: Session) -> dict[str, Any]:
    """Unified method distribution across audit_events and audit_events_noise.

    Cached for METHODS_TTL_SECONDS keyed by the bound engine. On any
    individual query failure we return empty rows for that table rather
    than 500 — partial answers are better than no answer for a dropdown
    / overview surface.
    """
    bind = db.get_bind()
    cache_key = id(bind)
    with _methods_cache_lock:
        cached = _methods_cache.get(cache_key)
    if cached is not None:
        return cached

    signal_rows = _query_signal_methods(db)
    noise_rows = _query_noise_methods(db)
    merged = _merge_method_rows(signal_rows, noise_rows)

    total_signal = sum(int(r.get("count", 0)) for r in signal_rows)
    total_noise = sum(int(r.get("count", 0)) for r in noise_rows)

    payload: dict[str, Any] = {
        "methods": merged,
        "total_signal_events": total_signal,
        "total_noise_events": total_noise,
        "generated_at": datetime.now(timezone.utc),
    }
    with _methods_cache_lock:
        _methods_cache[cache_key] = payload
    return payload
