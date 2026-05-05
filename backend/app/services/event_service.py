import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, defer, load_only

from backend.app.db.models import AuditEvent
from backend.app.services.filter_service import event_fingerprint, normalize_event, parse_event_timestamp
from src.product.event_normalization import canonical_resource_type

MAX_EVENT_LIMIT = 500
SIGNAL_FILTER_MAX_SCAN = 5000
SIGNAL_FILTER_BATCH_SIZE = 500
VALID_SIGNAL_TYPES = {"noise", "informational", "attention", "action_required"}
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
logger = logging.getLogger("auditlens.backend.events")
TIME_WINDOW_RE = re.compile(r"^([1-9][0-9]*)([mh])$")
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
    AuditEvent.source_ip,
    AuditEvent._source_context,
    AuditEvent._client_id,
    AuditEvent._connection_id,
    AuditEvent._request_id,
    AuditEvent.environment_id,
    AuditEvent.flink_region,
    AuditEvent.network_id,
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
    debug: dict[str, Any] | None = None


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
    return event


def upsert_event(db: Session, payload: dict[str, Any]) -> AuditEvent:
    return create_event(db, payload)


def get_event(db: Session, event_id: int) -> AuditEvent | None:
    return db.get(AuditEvent, event_id)


def _event_filter_conditions(
    *,
    time_window: str | None = None,
    resource_type: str | None = None,
    resource: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    result: str | None = None,
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
                func.lower(AuditEvent.summary).like(pattern),
            )
        )
    if action_category and action_category.strip():
        conditions.append(AuditEvent.action_category == action_category.strip())
    if actor and actor.strip():
        conditions.append(func.lower(AuditEvent.actor).like(f"%{actor.strip().lower()}%"))
    if result and result.strip():
        conditions.append(AuditEvent.result == result.strip())
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


def _matches_derived_filters(
    event: AuditEvent,
    signal_types: set[str],
    hide_noise: bool,
    impact_types: set[str] | None = None,
    change_types: set[str] | None = None,
) -> bool:
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
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    debug: bool = False,
    **filters: Any,
) -> EventListResult:
    limit = min(max(limit, 1), MAX_EVENT_LIMIT)
    offset = max(offset, 0)
    signal_types = _parse_signal_types(signal_type)
    impact_types = _parse_impact_types(impact_type)
    change_types = _parse_change_types(change_type)
    derived_filter_applied = bool(signal_types or impact_types or change_types) or hide_noise
    filters = _apply_derived_prefilters(filters, impact_types, change_types)
    active_filters = {key: value for key, value in filters.items() if isinstance(value, str) and value.strip()}
    conditions = _event_filter_conditions(**filters)
    count_query = select(func.count(AuditEvent.id))
    item_query = select(AuditEvent).options(load_only(*EVENT_LIST_COLUMNS), defer(AuditEvent.raw_payload_json, raiseload=True))
    if conditions:
        count_query = count_query.where(*conditions)
        item_query = item_query.where(*conditions)
    estimated_total = _estimate_unfiltered_total(db) if not active_filters else None
    pre_filter_total = int(estimated_total if estimated_total is not None else db.scalar(count_query) or 0)
    total = pre_filter_total
    if not derived_filter_applied:
        items = db.scalars(item_query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(limit).offset(offset)).all()
        return EventListResult(
            items=list(items),
            total=total,
            scanned_events=len(items),
            signal_filter_applied=False,
            hide_noise_applied=False,
            debug=_debug_info(db, filters, pre_filter_total, len(items), len(items), False) if debug else None,
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
        collected.extend(event for event in batch if _matches_derived_filters(event, signal_types, hide_noise, impact_types, change_types))
        if len(batch) < batch_size:
            break
    page = collected[offset : offset + limit]
    result_limit_reached = scanned >= SIGNAL_FILTER_MAX_SCAN and len(collected) >= offset + limit
    return EventListResult(
        items=page,
        total=len(collected),
        scanned_events=scanned,
        signal_filter_applied=bool(signal_types),
        hide_noise_applied=hide_noise,
        result_limit_reached=result_limit_reached,
        debug=_debug_info(db, filters, pre_filter_total, scanned, len(collected), True) if debug else None,
    )


def _debug_info(
    db: Session,
    filters: dict[str, Any],
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


def cleanup_retention(db: Session, retention_days: int, *, dry_run: bool = False) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(retention_days, 1))
    count_query = select(func.count(AuditEvent.id)).where(AuditEvent.timestamp < cutoff)
    deleted_count = int(db.scalar(count_query) or 0)
    if not dry_run and deleted_count:
        db.execute(delete(AuditEvent).where(AuditEvent.timestamp < cutoff))
        db.commit()
    logger.info(
        "retention cleanup complete dry_run=%s retention_days=%s cutoff=%s deleted_count=%s",
        dry_run,
        retention_days,
        cutoff.isoformat(),
        deleted_count,
    )
    return {"dry_run": dry_run, "retention_days": retention_days, "cutoff": cutoff.isoformat(), "deleted_count": deleted_count}


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
