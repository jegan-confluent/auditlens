import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, load_only

from backend.app.db.models import AuditEvent
from backend.app.services.filter_service import event_fingerprint, normalize_event, parse_event_timestamp

MAX_EVENT_LIMIT = 500
logger = logging.getLogger("auditlens.backend.events")
TIME_WINDOW_RE = re.compile(r"^([1-9][0-9]*)([mh])$")
EVENT_LIST_COLUMNS = (
    AuditEvent.id,
    AuditEvent.event_fingerprint,
    AuditEvent.timestamp,
    AuditEvent.result,
    AuditEvent.actor,
    AuditEvent.action,
    AuditEvent.normalized_action,
    AuditEvent.action_category,
    AuditEvent.resource_type,
    AuditEvent.resource_name,
    AuditEvent.resource_display,
    AuditEvent.cluster_id,
    AuditEvent.source_ip,
    AuditEvent.summary,
    AuditEvent.is_failure,
    AuditEvent.is_denied,
    AuditEvent.is_routine_noise,
)


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
        conditions.append(AuditEvent.resource_type == resource_type.strip())
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


def list_events(db: Session, *, limit: int = 100, offset: int = 0, **filters: Any) -> tuple[list[AuditEvent], int]:
    limit = min(max(limit, 1), MAX_EVENT_LIMIT)
    offset = max(offset, 0)
    active_filters = {key: value for key, value in filters.items() if isinstance(value, str) and value.strip()}
    conditions = _event_filter_conditions(**filters)
    count_query = select(func.count(AuditEvent.id))
    item_query = select(AuditEvent).options(load_only(*EVENT_LIST_COLUMNS))
    if conditions:
        count_query = count_query.where(*conditions)
        item_query = item_query.where(*conditions)
    estimated_total = _estimate_unfiltered_total(db) if not active_filters else None
    total = estimated_total if estimated_total is not None else db.scalar(count_query)
    items = db.scalars(item_query.order_by(AuditEvent.timestamp.desc()).limit(limit).offset(offset)).all()
    return list(items), int(total)


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
    statement = insert_fn(AuditEvent).values(rows).on_conflict_do_nothing(index_elements=["event_fingerprint"])
    result = db.execute(statement)
    db.commit()
    return int(result.rowcount or 0)


def upsert_events_sqlite(db: Session, payloads: list[dict[str, Any]]) -> int:
    return upsert_events(db, payloads)
