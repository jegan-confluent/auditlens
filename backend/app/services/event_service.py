import base64
import binascii
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, defer, load_only

from backend.app.db.models import AuditEvent, AuditEventTriage
from backend.app.services.filter_service import event_fingerprint, normalize_event, parse_event_timestamp
from backend.app.services.pattern_service import _norm, get_suppressed_combos
from backend.app.services.resource_service import upsert_resource_catalog
from backend.app.services.triage_service import attach_triage_snapshots, get_triage_snapshot
from src.product.event_normalization import canonical_resource_type

MAX_EVENT_LIMIT = 500

# Suppression cache — refreshed at most once per minute
_suppression_lock = threading.Lock()
_suppression_cache: tuple[float, set[tuple[str, str, str]]] | None = None
_suppression_ttl = 60.0
_suppression_table_missing = False
# Per-transaction statement_timeout for /events (Postgres). The default 30s
# pool-level timeout is exceeded by the decision-mode count() query on the
# production table; 120s matches /summary's allowance.
EVENTS_ROUTE_STATEMENT_TIMEOUT_MS = 120000
SIGNAL_FILTER_MAX_SCAN = 5000
SIGNAL_FILTER_BATCH_SIZE = 500
VALID_SIGNAL_TYPES = {"noise", "informational", "attention", "action_required"}
VALID_MODES = {"decision", "audit_trail"}
VALID_IMPACT_TYPES = {
    "constructive",
    "destructive",
    "configuration_change",
    "access_change",
    "authentication",
    "authorization_check",
    "read_only",
    "operational",
    "security_sensitive",
    "unknown",
}
VALID_CHANGE_TYPES = {"created", "deleted", "updated", "read/listed", "authenticated", "authorized", "denied", "configured", "unknown"}
CHANGE_TYPE_ALIASES = {
    "config": {"updated", "configured"},
    "configuration": {"updated", "configured"},
    "access": {"created", "deleted", "updated", "configured"},
    "read": {"read/listed"},
    "listed": {"read/listed"},
}
DECISION_ACTION_CATEGORIES = {"create", "delete", "modify", "api key"}
logger = logging.getLogger("auditlens.backend.events")
TIME_WINDOW_RE = re.compile(r"^([1-9][0-9]*)([mh])$")


def _get_suppressed_combos_cached(db: Session) -> set[tuple[str, str, str]]:
    global _suppression_cache, _suppression_table_missing
    if _suppression_table_missing:
        return set()
    with _suppression_lock:
        now = time.time()
        if _suppression_cache is not None:
            cached_at, combos = _suppression_cache
            if now - cached_at < _suppression_ttl:
                return combos
        try:
            combos = get_suppressed_combos(db)
        except Exception as exc:
            err = str(exc).lower()
            if "no such table" in err or "does not exist" in err or "relation" in err:
                _suppression_table_missing = True
                logger.warning(
                    "audit_event_patterns table not found; suppression disabled until migration 0009 is applied"
                )
            else:
                logger.warning("Failed to load suppressed patterns (non-fatal): %s", exc)
                # Cache empty set for the TTL so transient errors don't cause a
                # thundering herd of re-queries on every /events request.
                _suppression_cache = (now, set())
            return set()
        _suppression_cache = (now, combos)
        return combos


EVENT_LIST_COLUMNS = (
    AuditEvent.id,
    AuditEvent.event_fingerprint,
    AuditEvent.timestamp,
    AuditEvent.result,
    AuditEvent.actor,
    AuditEvent.actor_id,
    AuditEvent._actor_display_name,
    AuditEvent._actor_email,
    AuditEvent._actor_type,
    AuditEvent._actor_source,
    AuditEvent._actor_confidence,
    AuditEvent.actor_enriched_at,
    AuditEvent.action,
    AuditEvent.normalized_action,
    AuditEvent.action_category,
    AuditEvent.resource_type,
    AuditEvent.resource_name,
    AuditEvent.resource_display,
    AuditEvent.cluster_id,
    AuditEvent._cluster_name,
    AuditEvent.source_ip,
    AuditEvent._source_context,
    AuditEvent._client_id,
    AuditEvent._connection_id,
    AuditEvent._request_id,
    AuditEvent.environment_id,
    AuditEvent._environment_name,
    AuditEvent._parent_resource,
    AuditEvent._resource_scope,
    AuditEvent._resource_display_name,
    AuditEvent._resource_criticality,
    AuditEvent._blast_radius_hint,
    AuditEvent._production_hint,
    AuditEvent.flink_region,
    AuditEvent.network_id,
    AuditEvent._signal_type,
    AuditEvent._signal_reason,
    AuditEvent._impact_type,
    AuditEvent._risk_level,
    AuditEvent._change_type,
    AuditEvent._resource_family,
    AuditEvent._event_title,
    AuditEvent._event_summary,
    AuditEvent._decision_reason,
    AuditEvent._decision_label,
    AuditEvent._recommended_action,
    AuditEvent.summary,
    AuditEvent.is_failure,
    AuditEvent.is_denied,
    AuditEvent.is_routine_noise,
)


@dataclass
class EventListResult:
    items: list[AuditEvent]
    total: int
    scanned_events: int = 0
    signal_filter_applied: bool = False
    hide_noise_applied: bool = False
    result_limit_reached: bool = False
    next_cursor: str | None = None
    debug: dict[str, Any] | None = None


def _encode_cursor(timestamp: datetime, event_id: int) -> str:
    """Encode the (timestamp, id) keyset cursor as a URL-safe base64 string.

    The cursor is a stable opaque token; clients should not rely on its
    structure. We base64-encode a tiny JSON document so the same cursor
    survives round-trips through URL query strings.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    payload = json.dumps({"ts": timestamp.isoformat(), "id": int(event_id)}, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    if not cursor:
        raise ValueError("cursor must not be empty")
    try:
        # Re-pad — urlsafe_b64encode strips padding above for cleaner URLs.
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(decoded)
        ts_value = payload["ts"]
        id_value = int(payload["id"])
        ts = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ValueError("cursor is not a valid keyset cursor") from exc
    return ts, id_value


def parse_time_window(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().lower()
    match = TIME_WINDOW_RE.fullmatch(text)
    if not match:
        raise ValueError("time_window must use a positive minute or hour value such as 5m, 1h, or 24h")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "h":
        return datetime.now(timezone.utc) - timedelta(hours=amount)
    return datetime.now(timezone.utc) - timedelta(minutes=amount)


def create_event(db: Session, payload: dict[str, Any]) -> AuditEvent:
    normalized = normalize_event(payload)
    timestamp = parse_event_timestamp(payload)
    fingerprint = event_fingerprint(payload)
    event = AuditEvent(
        event_fingerprint=fingerprint,
        timestamp=timestamp,
        raw_payload_json=json.dumps(payload, sort_keys=True, default=str),
        **normalized,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
        existing = db.scalar(select(AuditEvent).where(AuditEvent.event_fingerprint == fingerprint))
        if existing is None:
            raise
        event = existing
    upsert_resource_catalog(db, event, payload, seen_at=timestamp)
    db.refresh(event)
    attach_triage_snapshots(db, [event])
    return event


def upsert_event(db: Session, payload: dict[str, Any]) -> AuditEvent:
    return create_event(db, payload)


def get_event(db: Session, event_id: int) -> AuditEvent | None:
    event = db.get(AuditEvent, event_id)
    if event is not None:
        setattr(event, "_triage_cache", get_triage_snapshot(db, event.event_fingerprint))
    return event


def _event_filter_conditions(
    *,
    time_window: str | None = None,
    resource_type: str | None = None,
    resource: str | None = None,
    cluster_name: str | None = None,
    environment_name: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    is_denied: bool | None = None,
) -> list[Any]:
    conditions: list[Any] = []
    since = parse_time_window(time_window)
    if since:
        conditions.append(AuditEvent.timestamp >= since)
    if resource_type and resource_type.strip():
        canonical = canonical_resource_type(resource_type)
        legacy_values = {canonical, canonical.title(), canonical.upper(), resource_type.strip()}
        legacy_values.add(canonical.replace("_", " ").title())
        if canonical == "role_binding":
            legacy_values.update({"ACL / RBAC", "RBAC", "ROLE_BINDING"})
        if canonical == "api_key":
            legacy_values.update({"API Key", "API_KEY"})
        if canonical == "schema_registry":
            legacy_values.update({"Schema Registry", "SCHEMA_REGISTRY"})
        if canonical == "compute_pool":
            legacy_values.update({"Compute Pool", "COMPUTE_POOL"})
        conditions.append(func.lower(AuditEvent.resource_type).in_({value.lower() for value in legacy_values if value}))
    if resource and resource.strip():
        pattern = f"%{resource.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(AuditEvent.resource_name).like(pattern),
                func.lower(AuditEvent.resource_display).like(pattern),
                func.lower(AuditEvent._resource_display_name).like(pattern),
                func.lower(AuditEvent.summary).like(pattern),
            )
        )
    if cluster_name and cluster_name.strip():
        pattern = f"%{cluster_name.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(AuditEvent._cluster_name).like(pattern),
                func.lower(AuditEvent.cluster_id).like(pattern),
            )
        )
    if environment_name and environment_name.strip():
        pattern = f"%{environment_name.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(AuditEvent._environment_name).like(pattern),
                func.lower(AuditEvent.environment_id).like(pattern),
            )
        )
    if action_category and action_category.strip():
        conditions.append(AuditEvent.action_category == action_category.strip())
    if actor and actor.strip():
        conditions.append(func.lower(AuditEvent.actor).like(f"%{actor.strip().lower()}%"))
    if action and action.strip():
        conditions.append(func.lower(AuditEvent.action).like(f"%{action.strip().lower()}%"))
    if result and result.strip():
        conditions.append(AuditEvent.result == result.strip())
    if is_denied is True:
        conditions.append(AuditEvent.is_denied.is_(True))
    return conditions


def build_event_query(db: Session, **filters: Any):
    query = select(AuditEvent)
    conditions = _event_filter_conditions(**filters)
    if conditions:
        query = query.where(*conditions)
    return query


def _estimate_unfiltered_total(db: Session) -> int | None:
    if db.get_bind().dialect.name != "postgresql":
        return None
    estimate = db.execute(
        text("select greatest(reltuples, 0)::bigint from pg_class where oid = 'audit_events'::regclass")
    ).scalar_one_or_none()
    return int(estimate) if estimate is not None else None


def _parse_signal_types(signal_type: str | None) -> set[str]:
    if not signal_type or not signal_type.strip():
        return set()
    values = {value.strip() for value in signal_type.split(",") if value.strip()}
    invalid = values - VALID_SIGNAL_TYPES
    if invalid:
        raise ValueError(f"signal_type must be one of: {', '.join(sorted(VALID_SIGNAL_TYPES))}")
    return values


def _parse_impact_types(impact_type: str | None) -> set[str]:
    if not impact_type or not impact_type.strip():
        return set()
    values = {value.strip() for value in impact_type.split(",") if value.strip()}
    invalid = values - VALID_IMPACT_TYPES
    if invalid:
        raise ValueError(f"impact_type must be one of: {', '.join(sorted(VALID_IMPACT_TYPES))}")
    return values


def _parse_change_types(change_type: str | None) -> set[str]:
    if not change_type or not change_type.strip():
        return set()
    values: set[str] = set()
    invalid: set[str] = set()
    for raw in (value.strip() for value in change_type.split(",") if value.strip()):
        if raw in CHANGE_TYPE_ALIASES:
            values.update(CHANGE_TYPE_ALIASES[raw])
        elif raw in VALID_CHANGE_TYPES:
            values.add(raw)
        else:
            invalid.add(raw)
    if invalid:
        raise ValueError(f"change_type must be one of: {', '.join(sorted(VALID_CHANGE_TYPES | set(CHANGE_TYPE_ALIASES)))}")
    return values


def _normalize_mode(mode: str | None) -> str:
    value = (mode or "decision").strip().lower()
    if value not in VALID_MODES:
        raise ValueError("mode must be decision or audit_trail")
    return value


def _decision_mode_condition():
    return or_(
        func.lower(AuditEvent._signal_type).in_({"action_required", "attention"}),
        func.lower(AuditEvent._impact_type).in_({"destructive", "configuration_change", "access_change", "security_sensitive"}),
        func.lower(AuditEvent._risk_level).in_({"medium", "high", "critical"}),
        func.lower(AuditEvent._change_type).in_({"created", "deleted", "updated", "configured", "denied"}),
        func.lower(AuditEvent.action_category).in_(DECISION_ACTION_CATEGORIES),
        AuditEvent.is_failure.is_(True),
        AuditEvent.is_denied.is_(True),
        func.lower(AuditEvent.result).in_({"failure", "denied"}),
        func.lower(AuditEvent.normalized_action).like("%acl%"),
        func.lower(AuditEvent.normalized_action).like("%api key%"),
        func.lower(AuditEvent.normalized_action).like("%apikey%"),
        func.lower(AuditEvent.normalized_action).like("%role%"),
        func.lower(AuditEvent.normalized_action).like("%grant%"),
        func.lower(AuditEvent.normalized_action).like("%revoke%"),
    )


def _matches_derived_filters(
    event: AuditEvent,
    signal_types: set[str],
    hide_noise: bool,
    impact_types: set[str] | None = None,
    change_types: set[str] | None = None,
    suppressed_combos: set[tuple[str, str, str]] | None = None,
) -> bool:
    if suppressed_combos and (event.actor, event.action, _norm(event.resource_name)) in suppressed_combos:
        return False
    if hide_noise and event.signal_type == "noise":
        return False
    if signal_types and event.signal_type not in signal_types:
        return False
    if impact_types and event.impact_type not in impact_types:
        return False
    if change_types and event.change_type not in change_types:
        return False
    return True


def _apply_derived_prefilters(filters: dict[str, Any], impact_types: set[str], change_types: set[str]) -> dict[str, Any]:
    next_filters = dict(filters)
    if not next_filters.get("action_category") and (impact_types == {"destructive"} or change_types == {"deleted"}):
        next_filters["action_category"] = "Delete"
    if not next_filters.get("result") and change_types == {"denied"}:
        next_filters["result"] = "Failure"
    return next_filters


def list_events_result(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    mode: str = "decision",
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    cursor: str | None = None,
    debug: bool = False,
    include_suppressed: bool = False,
    **filters: Any,
) -> EventListResult:
    limit = min(max(limit, 1), MAX_EVENT_LIMIT)
    offset = max(offset, 0)
    mode = _normalize_mode(mode)
    # Decision-mode count() over the OR-heavy predicate is expensive on the
    # production-sized table. Match the per-route timeout treatment we already
    # apply in summary_service so the route doesn't 500 under derived filters
    # (signal_type / hide_noise / impact_type) which now ship as the default.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {EVENTS_ROUTE_STATEMENT_TIMEOUT_MS}"))
    signal_types = _parse_signal_types(signal_type)
    impact_types = _parse_impact_types(impact_type)
    change_types = _parse_change_types(change_type)
    suppressed_combos: set[tuple[str, str, str]] = set()
    if not include_suppressed:
        suppressed_combos = _get_suppressed_combos_cached(db)
    use_suppression = bool(suppressed_combos)
    # signal_type is pushed into the SQL WHERE clause (indexed column) so totals
    # are accurate.  summary_service uses a 5000-row scan window for its digest
    # counts, so /summary action_required_count will differ from the exact total
    # returned here — that divergence is by design, not a filter mismatch.
    derived_filter_applied = bool(impact_types or change_types) or hide_noise or (use_suppression and mode == "decision")
    filters = _apply_derived_prefilters(filters, impact_types, change_types)
    active_filters = {key: value for key, value in {**filters, "mode": mode}.items() if isinstance(value, str) and value.strip()}
    conditions = _event_filter_conditions(**filters)
    if signal_types:
        if len(signal_types) == 1:
            conditions.append(AuditEvent._signal_type == next(iter(signal_types)))
        else:
            conditions.append(AuditEvent._signal_type.in_(signal_types))
    if mode == "decision":
        conditions.append(_decision_mode_condition())
    count_query = select(func.count(AuditEvent.id))
    item_query = select(AuditEvent).options(load_only(*EVENT_LIST_COLUMNS), defer(AuditEvent.raw_payload_json, raiseload=True))
    if conditions:
        count_query = count_query.where(*conditions)
        item_query = item_query.where(*conditions)
    estimated_total = _estimate_unfiltered_total(db) if not active_filters else None
    pre_filter_total = int(estimated_total if estimated_total is not None else db.scalar(count_query) or 0)
    total = pre_filter_total

    cursor_pair: tuple[datetime, int] | None = None
    if cursor:
        cursor_pair = _decode_cursor(cursor)

    if not derived_filter_applied:
        keyset_query = item_query
        if cursor_pair is not None:
            ts, last_id = cursor_pair
            # (timestamp, id) < (cursor_ts, cursor_id) — strictly older row in
            # newest-first ordering. We cannot rely on row tuple comparison on
            # SQLite, so spell it out as ts<cursor_ts OR (ts=cursor_ts AND id<cursor_id).
            keyset_query = keyset_query.where(
                or_(
                    AuditEvent.timestamp < ts,
                    and_(AuditEvent.timestamp == ts, AuditEvent.id < last_id),
                )
            )
            # Cursor mode is mutually exclusive with offset — using both is a
            # client bug, but we honour cursor and ignore offset.
            offset_for_query = 0
        else:
            offset_for_query = offset
        items = list(db.scalars(
            keyset_query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(limit).offset(offset_for_query)
        ).all())
        attach_triage_snapshots(db, items)
        if mode == "audit_trail" and use_suppression:
            for ev in items:
                if (ev.actor, ev.action, _norm(ev.resource_name)) in suppressed_combos:
                    setattr(ev, "_suppressed", True)
        next_cursor = None
        if items and len(items) == limit:
            tail = items[-1]
            next_cursor = _encode_cursor(tail.timestamp, tail.id)
        return EventListResult(
            items=list(items),
            total=total,
            scanned_events=len(items),
            signal_filter_applied=bool(signal_types),
            hide_noise_applied=False,
            next_cursor=next_cursor,
            debug=_debug_info(db, filters, mode, pre_filter_total, len(items), len(items), False) if debug else None,
        )

    collected: list[AuditEvent] = []
    scanned = 0
    db_offset = 0
    while scanned < SIGNAL_FILTER_MAX_SCAN and len(collected) < offset + limit:
        batch_size = min(SIGNAL_FILTER_BATCH_SIZE, SIGNAL_FILTER_MAX_SCAN - scanned)
        batch = list(db.scalars(item_query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(batch_size).offset(db_offset)).all())
        if not batch:
            break
        scanned += len(batch)
        db_offset += len(batch)
        combos_for_filter = suppressed_combos if mode == "decision" else None
        collected.extend(event for event in batch if _matches_derived_filters(event, signal_types, hide_noise, impact_types, change_types, combos_for_filter))
        if len(batch) < batch_size:
            break
    page = collected[offset : offset + limit]
    attach_triage_snapshots(db, page)
    if mode == "audit_trail" and use_suppression:
        for ev in page:
            if (ev.actor, ev.action, _norm(ev.resource_name)) in suppressed_combos:
                setattr(ev, "_suppressed", True)
    result_limit_reached = scanned >= SIGNAL_FILTER_MAX_SCAN
    # Derived filtering keeps offset semantics — keyset cursors are emitted
    # only on the SQL-only path because the derived prefilter loop scans a
    # bounded window in Python and the next-page boundary is offset-shaped.
    return EventListResult(
        items=page,
        total=len(collected),
        scanned_events=scanned,
        signal_filter_applied=bool(signal_types),
        hide_noise_applied=hide_noise,
        result_limit_reached=result_limit_reached,
        next_cursor=None,
        debug=_debug_info(db, filters, mode, pre_filter_total, scanned, len(collected), True) if debug else None,
    )


def _debug_info(
    db: Session,
    filters: dict[str, Any],
    mode: str,
    pre_filter_total: int,
    scanned_events: int,
    post_filter_total: int,
    derived_filter_applied: bool,
) -> dict[str, Any]:
    conditions = _event_filter_conditions(**filters)
    query = select(AuditEvent.resource_type, func.count(AuditEvent.id)).group_by(AuditEvent.resource_type)
    if conditions:
        query = query.where(*conditions)
    distribution: dict[str, int] = {}
    for resource_type, count in db.execute(query).all():
        key = canonical_resource_type(resource_type or "unknown")
        distribution[key] = distribution.get(key, 0) + int(count)
    return {
        "applied_filters": {key: value for key, value in filters.items() if value not in (None, "")},
        "mode": mode,
        "row_count_before_derived_filtering": pre_filter_total,
        "scanned_events": scanned_events,
        "row_count_after_derived_filtering": post_filter_total,
        "derived_filter_applied": derived_filter_applied,
        "resource_type_distribution": distribution,
    }


def list_events(db: Session, *, limit: int = 100, offset: int = 0, **filters: Any) -> tuple[list[AuditEvent], int]:
    result = list_events_result(db, limit=limit, offset=offset, **filters)
    return result.items, result.total


def list_failures(db: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[AuditEvent], int]:
    return list_events(db, limit=limit, offset=offset, result="Failure")


def list_deletions(db: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[AuditEvent], int]:
    return list_events(db, limit=limit, offset=offset, action_category="Delete")


def cleanup_retention(
    db: Session,
    retention_days: int,
    *,
    dry_run: bool = False,
    raw_payload_retention_days: int | None = None,
    noise_retention_days: int | None = None,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 1))

    raw_payloads_nulled = 0
    noise_deleted = 0

    # Step 1 — Null raw payloads older than raw_payload_retention_days
    if raw_payload_retention_days is not None and raw_payload_retention_days > 0:
        raw_cutoff = datetime.now(timezone.utc) - timedelta(days=raw_payload_retention_days)
        raw_count_q = select(func.count(AuditEvent.id)).where(
            AuditEvent.timestamp < raw_cutoff,
            AuditEvent.raw_payload_json.isnot(None),
            AuditEvent.raw_payload_json != "{}",
            AuditEvent.raw_payload_json != "",
        )
        raw_payloads_nulled = int(db.scalar(raw_count_q) or 0)
        if not dry_run and raw_payloads_nulled:
            batch_size = 1000
            total_nulled = 0
            while True:
                ids = list(db.scalars(
                    select(AuditEvent.id)
                    .where(
                        AuditEvent.timestamp < raw_cutoff,
                        AuditEvent.raw_payload_json.isnot(None),
                        AuditEvent.raw_payload_json != "{}",
                        AuditEvent.raw_payload_json != "",
                    )
                    .limit(batch_size)
                ).all())
                if not ids:
                    break
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(
                        text("UPDATE audit_events SET raw_payload_json = NULL WHERE id = ANY(:ids)"),
                        {"ids": ids},
                    )
                else:
                    db.execute(
                        text("UPDATE audit_events SET raw_payload_json = NULL WHERE id IN :ids"),
                        {"ids": tuple(ids)},
                    )
                db.commit()
                total_nulled += len(ids)
                if len(ids) < batch_size:
                    break
                import time as _time
                _time.sleep(0.01)
            raw_payloads_nulled = total_nulled

    # Step 2 — Delete old signal events (existing logic)
    count_query = select(func.count(AuditEvent.id)).where(AuditEvent.timestamp < cutoff)
    deleted_count = int(db.scalar(count_query) or 0)
    if not dry_run and deleted_count:
        # Belt-and-braces: explicitly clear triage rows first so legacy SQLite
        # installs (whose audit_event_triage table was created before the
        # ON DELETE CASCADE FK landed) do not leak orphans. On a fresh DB or on
        # Postgres the FK cascade would handle this automatically — running
        # the DELETE again is a cheap no-op there.
        fingerprints = list(
            db.scalars(select(AuditEvent.event_fingerprint).where(AuditEvent.timestamp < cutoff)).all()
        )
        if fingerprints:
            db.execute(
                delete(AuditEventTriage)
                .where(AuditEventTriage.event_fingerprint.in_(fingerprints))
                .execution_options(synchronize_session=False)
            )
        db.execute(
            delete(AuditEvent)
            .where(AuditEvent.timestamp < cutoff)
            .execution_options(synchronize_session=False)
        )
        db.commit()

    # Step 3 — Delete old noise rows
    if noise_retention_days is not None and noise_retention_days > 0:
        try:
            noise_cutoff = datetime.now(timezone.utc) - timedelta(days=noise_retention_days)
            noise_count_result = db.scalar(
                text("SELECT COUNT(*) FROM audit_events_noise WHERE timestamp < :cutoff"),
                {"cutoff": noise_cutoff},
            )
            noise_deleted = int(noise_count_result or 0)
            if not dry_run and noise_deleted:
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(text("SET LOCAL statement_timeout = 30000"))
                db.execute(
                    text("DELETE FROM audit_events_noise WHERE timestamp < :cutoff"),
                    {"cutoff": noise_cutoff},
                )
                db.commit()
        except Exception as exc:
            err = str(exc).lower()
            if "no such table" in err or "does not exist" in err:
                noise_deleted = 0
            else:
                logger.warning("noise retention cleanup failed: %s", exc)
                noise_deleted = 0

    logger.info(
        "retention cleanup complete dry_run=%s retention_days=%s deleted=%s raw_nulled=%s noise_deleted=%s",
        dry_run, retention_days, deleted_count, raw_payloads_nulled, noise_deleted,
    )
    return {
        "dry_run": dry_run,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "deleted_count": deleted_count,
        "raw_payloads_nulled": raw_payloads_nulled,
        "noise_deleted": noise_deleted,
    }


def upsert_events(db: Session, payloads: list[dict[str, Any]]) -> int:
    rows = []
    for payload in payloads:
        normalized = normalize_event(payload)
        rows.append(
            {
                "event_fingerprint": event_fingerprint(payload),
                "timestamp": parse_event_timestamp(payload),
                "raw_payload_json": json.dumps(payload, sort_keys=True, default=str),
                **normalized,
            }
        )
    if not rows:
        return 0
    dialect = db.get_bind().dialect.name
    insert_fn = postgres_insert if dialect == "postgresql" else sqlite_insert
    statement = insert_fn(AuditEvent.__table__).values(rows).on_conflict_do_nothing(index_elements=["event_fingerprint"])
    result = db.execute(statement)
    db.commit()
    return int(result.rowcount or 0)


def upsert_events_sqlite(db: Session, payloads: list[dict[str, Any]]) -> int:
    return upsert_events(db, payloads)
