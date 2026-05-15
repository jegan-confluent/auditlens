import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from time import sleep
from typing import Any

from sqlalchemy import and_, or_, select, text, tuple_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, load_only, sessionmaker

from backend.app.db.models import AuditEvent
from src.product.actor_enrichment import (
    clear_actor_enrichment_cache,
    enrich_actor,
    wait_for_iam_cache_ready,
)
from src.product.event_normalization import normalize_event
from src.product.resource_intelligence import extract_resource_context
from src.product.source_enrichment import extract_source_info
from backend.app.services.resource_service import upsert_resource_catalog
from backend.app.services import settings_service

logger = logging.getLogger("auditlens.backend.backfill")


@dataclass
class BackfillResult:
    scanned: int = 0
    updated: int = 0
    source_updated: int = 0
    decision_updated: int = 0
    invalid_json: int = 0
    dry_run: bool = True
    force: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "updated": self.updated,
            "source_updated": self.source_updated,
            "decision_updated": self.decision_updated,
            "invalid_json": self.invalid_json,
            "dry_run": self.dry_run,
            "force": self.force,
        }


SOURCE_FIELDS = ("source_ip", "source_context", "client_id", "connection_id", "request_id", "environment_id", "flink_region", "network_id")
DECISION_FIELDS = (
    "signal_type",
    "signal_reason",
    "impact_type",
    "risk_level",
    "change_type",
    "resource_family",
    "event_title",
    "event_summary",
    "decision_reason",
    "decision_label",
    "recommended_action",
)
FIELD_ATTRS = {
    "source_ip": "source_ip",
    "source_context": "_source_context",
    "client_id": "_client_id",
    "connection_id": "_connection_id",
    "request_id": "_request_id",
    "environment_id": "environment_id",
    "flink_region": "flink_region",
    "network_id": "network_id",
    "signal_type": "_signal_type",
    "signal_reason": "_signal_reason",
    "impact_type": "_impact_type",
    "risk_level": "_risk_level",
    "change_type": "_change_type",
    "resource_family": "_resource_family",
    "event_title": "_event_title",
    "event_summary": "_event_summary",
    "decision_reason": "_decision_reason",
    "decision_label": "_decision_label",
    "recommended_action": "_recommended_action",
}

RESOURCE_FIELD_ATTRS = {
    "resource_type": "resource_type",
    "resource_name": "resource_name",
    "resource_display": "resource_display",
    "cluster_id": "cluster_id",
    "cluster_name": "_cluster_name",
    "environment_id": "environment_id",
    "environment_name": "_environment_name",
    "parent_resource": "_parent_resource",
    "resource_scope": "_resource_scope",
    "resource_display_name": "_resource_display_name",
    "resource_criticality": "_resource_criticality",
    "blast_radius_hint": "_blast_radius_hint",
    "production_hint": "_production_hint",
}
RESOURCE_FIELDS = tuple(RESOURCE_FIELD_ATTRS.keys())
RESOURCE_PLACEHOLDERS = {None, "", "-", "Unknown", "unknown", "Not provided by audit event"}


def _load_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _client_address_ip(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("ip") or first.get("address") or "").strip()
        return str(first).strip()
    if isinstance(value, dict):
        return str(value.get("ip") or value.get("address") or "").strip()
    return str(value).strip() if value is not None else ""


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _has_column(event: AuditEvent, column_name: str) -> bool:
    try:
        return hasattr(type(event), column_name) or hasattr(event, column_name)
    except Exception as exc:
        logger.debug("_has_column check failed for %s: %s", column_name, exc)
        return False


def _top_level_keys(payload: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in payload.keys())


def _effective_since(*, hours: int | None = None, since: datetime | None = None) -> datetime | None:
    candidates: list[datetime] = []
    if since is not None:
        candidates.append(since)
    if hours is not None:
        if hours < 0:
            raise ValueError("hours must be >= 0")
        candidates.append(datetime.now(timezone.utc) - timedelta(hours=hours))
    if not candidates:
        return None
    # max() picks the most-recent cutoff (most restrictive); both callers supply
    # hours and/or since as separate knobs and expect the tighter bound to win.
    result = max(candidates)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _selected_attrs(fields: tuple[str, ...]) -> list[str]:
    return [FIELD_ATTRS[field] for field in fields if field in FIELD_ATTRS]


def _source_ip_from_payload(payload: dict[str, Any], event: AuditEvent | None = None) -> str:
    data_json = _load_json(payload.get("data_json"))
    event_data_json = _load_json(getattr(event, "data_json", None)) if event is not None and _has_column(event, "data_json") else {}
    row_data = _load_json(payload.get("data")) if isinstance(payload.get("data"), dict) else {}
    data = data_json or event_data_json or row_data
    request_metadata = _nested(data, "requestMetadata") or payload.get("requestMetadata") or {}
    return (
        str(payload.get("clientIp") or "").strip()
        or str(payload.get("client_ip") or "").strip()
        or _client_address_ip(_nested(payload, "requestMetadata", "clientAddress"))
        or _client_address_ip(_nested(data, "requestMetadata", "clientAddress"))
        or _as_text(_nested(data, "clientIp"))
        or _as_text(_nested(data, "client_ip"))
        or _client_address_ip(_nested(request_metadata, "clientAddress"))
        or _client_address_ip(payload.get("clientAddress"))
    )


def _selected_fields(source_fields: bool, decision_fields: bool) -> tuple[str, ...]:
    fields: list[str] = []
    if source_fields:
        fields.extend(SOURCE_FIELDS)
    if decision_fields:
        fields.extend(DECISION_FIELDS)
    return tuple(fields)


def _is_placeholder(value: Any) -> bool:
    return value in RESOURCE_PLACEHOLDERS


def _resource_missing_condition(column: Any):
    return or_(
        column.is_(None),
        column == "",
        column == "-",
        column == "Unknown",
        column == "unknown",
        column == "Not provided by audit event",
    )


def _resource_batch_query(
    *,
    since: datetime | None,
    until: datetime | None,
    force: bool,
    cursor: tuple[datetime, int] | None,
    batch_size: int,
):
    columns = [
        AuditEvent.id,
        AuditEvent.timestamp,
        AuditEvent.summary,
        AuditEvent.raw_payload_json,
        AuditEvent.resource_type,
        AuditEvent.resource_name,
        AuditEvent.resource_display,
        AuditEvent.cluster_id,
        AuditEvent.environment_id,
        AuditEvent.flink_region,
        AuditEvent.network_id,
        AuditEvent._cluster_name,
        AuditEvent._environment_name,
        AuditEvent._parent_resource,
        AuditEvent._resource_scope,
        AuditEvent._resource_display_name,
        AuditEvent._resource_criticality,
        AuditEvent._blast_radius_hint,
        AuditEvent._production_hint,
    ]
    query = select(AuditEvent).options(load_only(*columns))
    if since is not None:
        query = query.where(AuditEvent.timestamp >= since)
    if until is not None:
        query = query.where(AuditEvent.timestamp <= until)
    if not force:
        query = query.where(
            or_(
                _resource_missing_condition(AuditEvent.resource_display),
                _resource_missing_condition(AuditEvent.resource_type),
                _resource_missing_condition(AuditEvent.resource_name),
                _resource_missing_condition(AuditEvent._cluster_name),
                _resource_missing_condition(AuditEvent._environment_name),
                _resource_missing_condition(AuditEvent._parent_resource),
                _resource_missing_condition(AuditEvent._resource_scope),
                _resource_missing_condition(AuditEvent._resource_display_name),
                _resource_missing_condition(AuditEvent._resource_criticality),
                _resource_missing_condition(AuditEvent._blast_radius_hint),
                _resource_missing_condition(AuditEvent._production_hint),
            )
        )
    if cursor is not None:
        query = query.where(tuple_(AuditEvent.timestamp, AuditEvent.id) > cursor)
    return query.order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc()).limit(batch_size)


def _resource_updates(event: AuditEvent, payload: dict[str, Any], *, force: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    context = extract_resource_context(payload, event)
    event_fields = context.to_event_fields()
    event_fields["resource_display"] = context.resource_display_name
    updates: dict[str, Any] = {}
    for field, attr in RESOURCE_FIELD_ATTRS.items():
        current = getattr(event, attr, None)
        next_value = event_fields.get(field)
        if _is_placeholder(next_value):
            continue
        if force or _is_placeholder(current):
            updates[field] = next_value
    return updates, {
        "resource_id": context.resource_id,
        "resource_type": context.resource_type,
        "resource_name": context.resource_name,
        "resource_display_name": context.resource_display_name,
        "cluster_id": context.cluster_id,
        "cluster_name": context.cluster_name,
        "environment_id": context.environment_id,
        "environment_name": context.environment_name,
        "parent_resource": context.parent_resource,
        "resource_scope": context.resource_scope,
        "resource_criticality": context.resource_criticality,
        "blast_radius_hint": context.blast_radius_hint,
        "production_hint": context.production_hint,
        "resource_source": context.resource_source,
        "payload": payload,
    }


def _field_value_map(
    payload: dict[str, Any],
    event: AuditEvent,
    *,
    source_fields: bool,
    decision_fields: bool,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if source_fields:
        source_info = extract_source_info(payload, event)
        source_ip = _source_ip_from_payload(payload, event) or source_info.get("source_ip")
        for field in SOURCE_FIELDS:
            values[field] = source_ip if field == "source_ip" else source_info.get(field)
    if decision_fields:
        decision = normalize_event(payload)
        for field in DECISION_FIELDS:
            values[field] = decision.get(field)
    return values


def _row_plan(
    event: AuditEvent,
    payload: dict[str, Any],
    *,
    source_fields: bool,
    decision_fields: bool,
    force: bool,
) -> dict[str, Any]:
    has_raw_payload = bool(event.raw_payload_json)
    has_data_json_column = _has_column(event, "data_json")
    selected_fields = _selected_fields(source_fields, decision_fields)
    if not _has_column(event, "source_ip"):
        return {
            "id": event.id,
            "has_raw_payload_json": has_raw_payload,
            "has_data_json_column": has_data_json_column,
            "raw_payload_top_level_keys": _top_level_keys(payload) if has_raw_payload else [],
            "extracted_source_ip": "",
            "extracted_source_context": "",
            "extracted_signal_type": "",
            "extracted_impact_type": "",
            "update_reason": "source_ip_column_missing",
            "would_update": False,
            "updates": {},
        }
    if not has_raw_payload:
        return {
            "id": event.id,
            "has_raw_payload_json": False,
            "has_data_json_column": has_data_json_column,
            "raw_payload_top_level_keys": [],
            "extracted_source_ip": "",
            "extracted_source_context": "",
            "extracted_signal_type": "",
            "extracted_impact_type": "",
            "update_reason": "no_raw_payload",
            "would_update": False,
            "updates": {},
        }

    extracted = _field_value_map(payload, event, source_fields=source_fields, decision_fields=decision_fields)
    updates: dict[str, Any] = {}
    for field in selected_fields:
        current = getattr(event, FIELD_ATTRS[field], None)
        next_value = extracted.get(field)
        if next_value in (None, ""):
            continue
        if force or current in (None, ""):
            updates[field] = next_value
    source_values = {field: extracted.get(field) for field in SOURCE_FIELDS}
    decision_values = {field: extracted.get(field) for field in DECISION_FIELDS}
    return {
        "id": event.id,
        "has_raw_payload_json": True,
        "has_data_json_column": has_data_json_column,
        "raw_payload_top_level_keys": _top_level_keys(payload),
        "extracted_source_ip": _as_text(source_values.get("source_ip")),
        "extracted_source_context": _as_text(source_values.get("source_context")),
        "extracted_signal_type": _as_text(decision_values.get("signal_type")),
        "extracted_impact_type": _as_text(decision_values.get("impact_type")),
        "update_reason": "would_update" if updates else "already_has_fields",
        "would_update": bool(updates),
        "updates": updates,
    }


def _needs_source_backfill(event: AuditEvent, *, force: bool) -> bool:
    if force:
        return True
    return any(getattr(event, FIELD_ATTRS[field]) in (None, "") for field in SOURCE_FIELDS)


def _build_batch_query(
    *,
    since: datetime | None,
    until: datetime | None,
    force: bool,
    source_fields: bool,
    decision_fields: bool,
    target_id: int | None,
    order: str,
    cursor: tuple[datetime, int] | None,
    batch_size: int,
):
    query = select(AuditEvent)
    if target_id is not None:
        query = query.where(AuditEvent.id == target_id)
    else:
        if since is not None:
            query = query.where(AuditEvent.timestamp >= since)
        if until is not None:
            query = query.where(AuditEvent.timestamp <= until)
        if not force:
            missing_groups = []
            if source_fields:
                missing_groups.append(
                    or_(
                        AuditEvent.source_ip.is_(None),
                        AuditEvent._source_context.is_(None),
                        AuditEvent._client_id.is_(None),
                        AuditEvent._connection_id.is_(None),
                        AuditEvent._request_id.is_(None),
                        AuditEvent.environment_id.is_(None),
                        AuditEvent.flink_region.is_(None),
                        AuditEvent.network_id.is_(None),
                    )
                )
                query = query.where(
                    or_(
                        AuditEvent.raw_payload_json.contains('"clientIp"'),
                        AuditEvent.raw_payload_json.contains('"client_ip"'),
                        AuditEvent.raw_payload_json.contains('"requestMetadata"'),
                        AuditEvent.raw_payload_json.contains('"clientAddress"'),
                        AuditEvent.raw_payload_json.contains('"data_json"'),
                    )
                )
            if decision_fields:
                missing_groups.append(
                    or_(
                        AuditEvent._signal_type.is_(None),
                        AuditEvent._signal_reason.is_(None),
                        AuditEvent._impact_type.is_(None),
                        AuditEvent._risk_level.is_(None),
                        AuditEvent._change_type.is_(None),
                        AuditEvent._resource_family.is_(None),
                        AuditEvent._event_title.is_(None),
                        AuditEvent._event_summary.is_(None),
                        AuditEvent._decision_reason.is_(None),
                        AuditEvent._decision_label.is_(None),
                        AuditEvent._recommended_action.is_(None),
                    )
                )
            if missing_groups:
                query = query.where(or_(*missing_groups))
        if cursor is not None:
            if order == "newest":
                query = query.where(tuple_(AuditEvent.timestamp, AuditEvent.id) < cursor)
            else:
                query = query.where(tuple_(AuditEvent.timestamp, AuditEvent.id) > cursor)
    if order == "newest":
        query = query.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
    else:
        query = query.order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
    return query.limit(batch_size)


def backfill_source_fields_from_raw_payload(
    db: Session,
    *,
    dry_run: bool = True,
    limit: int = 1000,
    force: bool = False,
    source_fields: bool = True,
    decision_fields: bool = False,
    hours: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: str = "oldest",
    sleep_ms: int = 0,
    target_id: int | None = None,
    debug_sample: int = 0,
) -> dict[str, Any]:
    if not source_fields and not decision_fields:
        raise ValueError("choose at least one backfill target: source_fields or decision_fields")
    limit = max(1, min(int(limit), 10000))
    order = order.lower().strip()
    if order not in {"oldest", "newest"}:
        raise ValueError("order must be oldest or newest")
    sleep_ms = max(0, int(sleep_ms))
    effective_since = _effective_since(hours=hours, since=_normalize_dt(since))
    effective_until = _normalize_dt(until)
    result = BackfillResult(dry_run=dry_run, force=force)
    processed = 0
    batch_size = min(limit, 1000)
    _CURSOR_CATEGORY = "backfill"
    _CURSOR_KEY = "source_fields_cursor"
    cursor: tuple[datetime, int] | None = None
    if not dry_run and target_id is None:
        _saved = settings_service.get(db, _CURSOR_CATEGORY, _CURSOR_KEY)
        if _saved:
            try:
                _ts_str, _id_str = _saved.rsplit("|", 1)
                cursor = (datetime.fromisoformat(_ts_str), int(_id_str))
                logger.info("backfill_source_fields: resuming from cursor %s", cursor)
            except Exception as exc:
                logger.warning("backfill_source_fields: invalid cursor '%s', restarting from beginning: %s", _saved, exc)
                cursor = None
    while processed < limit:
        current_limit = 1 if target_id is not None else min(batch_size, limit - processed)
        query = _build_batch_query(
            since=effective_since,
            until=effective_until,
            force=force,
            source_fields=source_fields,
            decision_fields=decision_fields,
            target_id=target_id,
            order=order,
            cursor=cursor,
            batch_size=current_limit,
        )
        batch = db.scalars(query).all()
        if not batch:
            break
        for event in batch:
            processed += 1
            result.scanned += 1
            try:
                payload = json.loads(event.raw_payload_json) if event.raw_payload_json else {}
            except json.JSONDecodeError:
                result.invalid_json += 1
                if debug_sample > 0:
                    decision = _row_plan(event, {}, source_fields=source_fields, decision_fields=decision_fields, force=force)
                    print(
                        "row "
                        f"id={decision['id']} "
                        f"has_raw_payload_json={'yes' if decision['has_raw_payload_json'] else 'no'} "
                        f"has_data_json_column={'yes' if decision['has_data_json_column'] else 'no'} "
                        f"raw_payload_top_level_keys={','.join(decision['raw_payload_top_level_keys']) or '-'} "
                        f"extracted_source_ip={decision['extracted_source_ip'] or '-'} "
                        f"extracted_source_context={decision['extracted_source_context'] or '-'} "
                        f"extracted_signal_type={decision['extracted_signal_type'] or '-'} "
                        f"extracted_impact_type={decision['extracted_impact_type'] or '-'} "
                        f"update_reason={decision['update_reason']}"
                    )
                    debug_sample -= 1
                continue
            plan = _row_plan(event, payload, source_fields=source_fields, decision_fields=decision_fields, force=force)
            if plan["updates"]:
                result.updated += 1
                if source_fields:
                    result.source_updated += int(any(field in plan["updates"] for field in SOURCE_FIELDS))
                if decision_fields:
                    result.decision_updated += int(any(field in plan["updates"] for field in DECISION_FIELDS))
                if not dry_run:
                    for field, value in plan["updates"].items():
                        setattr(event, FIELD_ATTRS[field], value)
            if debug_sample > 0:
                print(
                    "row "
                    f"id={plan['id']} "
                    f"has_raw_payload_json={'yes' if plan['has_raw_payload_json'] else 'no'} "
                    f"has_data_json_column={'yes' if plan['has_data_json_column'] else 'no'} "
                    f"raw_payload_top_level_keys={','.join(plan['raw_payload_top_level_keys']) or '-'} "
                    f"extracted_source_ip={plan['extracted_source_ip'] or '-'} "
                    f"extracted_source_context={plan['extracted_source_context'] or '-'} "
                    f"extracted_signal_type={plan['extracted_signal_type'] or '-'} "
                    f"extracted_impact_type={plan['extracted_impact_type'] or '-'} "
                    f"update_reason={plan['update_reason']}"
                )
                debug_sample -= 1
            cursor = (event.timestamp, event.id)
        if not dry_run:
            db.commit()
            if cursor is not None and target_id is None:
                settings_service.set(db, _CURSOR_CATEGORY, _CURSOR_KEY,
                                     f"{cursor[0].isoformat()}|{cursor[1]}")
        if target_id is not None:
            break
        if len(batch) < current_limit:
            if not dry_run:
                settings_service.delete(db, _CURSOR_CATEGORY, _CURSOR_KEY)
            break
        if sleep_ms > 0 and processed < limit:
            sleep(sleep_ms / 1000.0)
    else:
        if not dry_run:
            settings_service.delete(db, _CURSOR_CATEGORY, _CURSOR_KEY)
    logger.info(
        "field backfill complete scanned=%s updated=%s source_updated=%s decision_updated=%s invalid_json=%s dry_run=%s force=%s source_fields=%s decision_fields=%s",
        result.scanned,
        result.updated,
        result.source_updated,
        result.decision_updated,
        result.invalid_json,
        dry_run,
        force,
        source_fields,
        decision_fields,
    )
    return result.as_dict()


def backfill_resource_intelligence_from_raw_payload(
    db: Session,
    *,
    dry_run: bool = True,
    limit: int = 1000,
    force: bool = False,
    hours: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    batch_size: int = 250,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100000))
    batch_size = max(1, min(int(batch_size), limit))
    effective_since = _effective_since(hours=hours, since=_normalize_dt(since))
    effective_until = _normalize_dt(until)
    processed = 0
    scanned = 0
    updated = 0
    skipped = 0
    invalid_json = 0
    catalog_upserted = 0
    catalog_failed = 0
    cursor: tuple[datetime, int] | None = None
    catalog_session_factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False, future=True)
    while processed < limit:
        current_limit = min(batch_size, limit - processed)
        batch = db.scalars(
            _resource_batch_query(
                since=effective_since,
                until=effective_until,
                force=force,
                cursor=cursor,
                batch_size=current_limit,
            )
        ).all()
        if not batch:
            break
        changed_events: list[tuple[AuditEvent, dict[str, Any], dict[str, Any]]] = []
        catalog_payloads: list[tuple[dict[str, Any], datetime]] = []
        for event in batch:
            processed += 1
            scanned += 1
            try:
                payload = json.loads(event.raw_payload_json) if event.raw_payload_json else {}
            except json.JSONDecodeError:
                invalid_json += 1
                cursor = (event.timestamp, event.id)
                continue
            try:
                updates, catalog_entry = _resource_updates(event, payload, force=force)
            except Exception as exc:  # pragma: no cover - best-effort enrichment
                logger.debug("resource intelligence recompute failed for event_id=%s: %s", event.id, exc)
                skipped += 1
                cursor = (event.timestamp, event.id)
                continue
            if updates:
                changed_events.append((event, updates, catalog_entry))
            else:
                skipped += 1
                catalog_payloads.append((catalog_entry, event.timestamp))
            cursor = (event.timestamp, event.id)
        updated += len(changed_events)
        if not dry_run and changed_events:
            for event, updates, _ in changed_events:
                for field, value in updates.items():
                    setattr(event, RESOURCE_FIELD_ATTRS[field], value)
            db.commit()
        elif not dry_run:
            db.rollback()
        if dry_run:
            catalog_upserted += len(changed_events) + len(catalog_payloads)
        else:
            with catalog_session_factory() as catalog_db:
                for event, updates, catalog_entry in changed_events:
                    try:
                        upsert_resource_catalog(
                            catalog_db,
                            event=event,
                            payload=catalog_entry["payload"],
                            seen_at=event.timestamp,
                            raise_on_error=True,
                        )
                        catalog_upserted += 1
                    except Exception as exc:  # pragma: no cover - best-effort enrichment
                        catalog_failed += 1
                        logger.debug("resource catalog backfill failed for event_id=%s: %s", event.id, exc)
                for payload_entry, seen_at in catalog_payloads:
                    try:
                        upsert_resource_catalog(
                            catalog_db,
                            payload=payload_entry["payload"],
                            seen_at=seen_at,
                            raise_on_error=True,
                        )
                        catalog_upserted += 1
                    except Exception as exc:  # pragma: no cover - best-effort enrichment
                        catalog_failed += 1
                        logger.debug("resource catalog backfill failed: %s", exc)
        if len(batch) < current_limit:
            break
    logger.info(
        "resource intelligence backfill complete scanned=%s updated=%s skipped=%s catalog_upserted=%s catalog_failed=%s invalid_json=%s dry_run=%s force=%s",
        scanned,
        updated,
        skipped,
        catalog_upserted,
        catalog_failed,
        invalid_json,
        dry_run,
        force,
    )
    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "catalog_upserted": catalog_upserted,
        "catalog_failed": catalog_failed,
        "invalid_json": invalid_json,
        "dry_run": dry_run,
        "force": force,
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 5: Backfill of legacy "Unknown user/SA/principal" rows.
# Older forwarder builds wrote those placeholders into actor_display_name
# before the raw-ID fallback existed. This job re-resolves them via the
# enrichment chain (actor_mappings.yml → IAM cache → audit-event name →
# raw actor ID), updates the row, and records progress for the admin
# status endpoint.
# ──────────────────────────────────────────────────────────────────────

_UNKNOWN_DISPLAY_NAMES = (
    "Unknown user",
    "Unknown service account",
    "Unknown principal",
    "Unknown actor",
)
_ACTOR_BACKFILL_BATCH_SIZE = 500
_ACTOR_BACKFILL_PROGRESS_LOG_EVERY = 10000
_ACTOR_BACKFILL_BATCH_SLEEP_MS = 10
_ACTOR_BACKFILL_STATEMENT_TIMEOUT_MS = 300000  # 5 minutes; full-table scan on first run

_actor_backfill_lock = threading.Lock()
_actor_backfill_state: dict[str, Any] = {
    "status": "idle",  # idle | running | complete | error
    "started_at": None,
    "completed_at": None,
    "dry_run": None,
    "progress": {
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    },
    "error": None,
}


def get_actor_backfill_status() -> dict[str, Any]:
    """Snapshot of the current/last actor-display-name backfill run."""
    with _actor_backfill_lock:
        return {
            "status": _actor_backfill_state["status"],
            "started_at": _actor_backfill_state["started_at"],
            "completed_at": _actor_backfill_state["completed_at"],
            "dry_run": _actor_backfill_state["dry_run"],
            "progress": dict(_actor_backfill_state["progress"]),
            "error": _actor_backfill_state["error"],
        }


def start_actor_display_name_backfill(engine: Engine, *, dry_run: bool) -> dict[str, Any]:
    """Spawn a single-flight backfill thread; return current state."""
    with _actor_backfill_lock:
        if _actor_backfill_state["status"] == "running":
            return {
                "status": "running",
                "started_at": _actor_backfill_state["started_at"],
                "dry_run": _actor_backfill_state["dry_run"],
                "progress": dict(_actor_backfill_state["progress"]),
            }
        _actor_backfill_state["status"] = "running"
        _actor_backfill_state["started_at"] = datetime.now(timezone.utc).isoformat()
        _actor_backfill_state["completed_at"] = None
        _actor_backfill_state["dry_run"] = bool(dry_run)
        _actor_backfill_state["progress"] = {
            "scanned": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }
        _actor_backfill_state["error"] = None

    thread = threading.Thread(
        target=_actor_display_name_backfill_thread,
        args=(engine, bool(dry_run)),
        name="actor-display-name-backfill",
        daemon=True,
    )
    thread.start()
    return {"status": "started", "dry_run": bool(dry_run)}


def _actor_display_name_backfill_thread(engine: Engine, dry_run: bool) -> None:
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        with factory() as db:
            result = backfill_actor_display_names(db, dry_run=dry_run)
        with _actor_backfill_lock:
            _actor_backfill_state["status"] = "complete"
            _actor_backfill_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _actor_backfill_state["progress"] = {
                "scanned": result.get("scanned", 0),
                "updated": result.get("updated", 0),
                "skipped": result.get("skipped", 0),
                "errors": result.get("errors", 0),
            }
    except Exception as exc:
        logger.exception("actor-display-name backfill failed: %s", exc)
        with _actor_backfill_lock:
            _actor_backfill_state["status"] = "error"
            _actor_backfill_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            _actor_backfill_state["error"] = str(exc)


def _resolve_actor_display_name(event: AuditEvent) -> dict[str, str | None] | None:
    """Try mapping → IAM → audit-event name → raw ID via enrich_actor.

    Returns an updates dict with the new display_name/source/confidence,
    or None if the resolution gave back the same placeholder we started
    with (don't burn an UPDATE on a no-op).
    """
    raw_actor = event.actor or ""
    enriched = enrich_actor(raw_actor, event.subject or "", event.subject_type or "")
    new_name = (enriched.get("actor_display_name") or "").strip()
    if not new_name:
        # No mapping, no IAM hit, no event-derived name, no raw ID —
        # surface the raw actor field instead so the row stops looking
        # like it has an unknown placeholder.
        new_name = raw_actor or ""
    if not new_name or new_name in _UNKNOWN_DISPLAY_NAMES:
        # Genuinely nothing to update with — but still mark the source
        # as "fallback" so downstream filters know enrichment ran.
        return None
    return {
        "actor_display_name": new_name,
        "actor_source": enriched.get("actor_source") or "fallback",
        "actor_confidence": enriched.get("actor_confidence") or "low",
    }


def backfill_actor_display_names(
    db: Session,
    *,
    dry_run: bool = True,
    iam_cache_wait_seconds: float = 30.0,
) -> dict[str, Any]:
    """Re-resolve rows where actor_display_name is a legacy "Unknown X".

    Cursor-based, batched on id ASC. Idempotent — once a row's display
    name is no longer in the placeholder set, subsequent runs skip it.
    """
    # Drop any cached enrichment results from prior runs so freshly-loaded
    # actor_mappings.yml takes effect mid-process.
    clear_actor_enrichment_cache()
    if not wait_for_iam_cache_ready(iam_cache_wait_seconds):
        logger.warning(
            "actor backfill: IAM cache not ready after %.0fs — proceeding with mappings + raw-ID fallback only",
            iam_cache_wait_seconds,
        )

    is_postgres = db.get_bind().dialect.name == "postgresql"

    scanned = 0
    updated = 0
    skipped = 0
    errors = 0
    # Three sequential passes, mutually exclusive — each targets a single
    # indexed condition so no OR forces a full sequential scan.
    # Pass 0 uses the partial index on actor_confidence = 'low' (migration 0019).
    # Passes 1 and 2 exclude confidence='low' rows (already owned by pass 0)
    # via IS DISTINCT FROM so that rows are never double-counted across passes.
    _not_low = AuditEvent._actor_confidence.is_distinct_from("low")
    _PASSES = [
        ("confidence_low",
         AuditEvent._actor_confidence == "low"),
        ("unknown_names",
         and_(AuditEvent._actor_display_name.in_(_UNKNOWN_DISPLAY_NAMES), _not_low)),
        ("raw_actor",
         and_(AuditEvent._actor_display_name == AuditEvent.actor,
              AuditEvent._actor_display_name.notin_(_UNKNOWN_DISPLAY_NAMES),
              _not_low)),
    ]
    pass_idx = 0
    last_id: int | None = None

    while pass_idx < len(_PASSES):
        pass_name, filter_clause = _PASSES[pass_idx]

        if is_postgres:
            db.execute(
                text(
                    f"SET LOCAL statement_timeout = {_ACTOR_BACKFILL_STATEMENT_TIMEOUT_MS}"
                )
            )
        logger.info(
            "actor-display-name backfill: fetching next batch (pass=%s, after_id=%s, timeout=300s)",
            pass_name,
            last_id,
        )
        query = (
            select(AuditEvent)
            .options(load_only(
                AuditEvent.id,
                AuditEvent.actor,
                AuditEvent._actor_display_name,
                AuditEvent._actor_source,
                AuditEvent._actor_confidence,
            ))
            .where(filter_clause)
            .order_by(AuditEvent.id.asc())
            .limit(_ACTOR_BACKFILL_BATCH_SIZE)
        )
        if last_id is not None:
            query = query.where(AuditEvent.id > last_id)
        batch = db.scalars(query).all()
        if not batch:
            pass_idx += 1
            last_id = None
            continue

        batch_last_id: int | None = None
        for event in batch:
            scanned += 1
            batch_last_id = event.id
            try:
                updates = _resolve_actor_display_name(event)
            except Exception as exc:
                errors += 1
                logger.debug(
                    "actor backfill resolve failed for event_id=%s: %s",
                    event.id,
                    exc,
                )
                continue
            if not updates:
                skipped += 1
                continue
            if dry_run:
                updated += 1
                continue
            try:
                event._actor_display_name = updates["actor_display_name"]
                event._actor_source = updates["actor_source"]
                event._actor_confidence = updates["actor_confidence"]
                updated += 1
            except Exception as exc:
                errors += 1
                logger.debug(
                    "actor backfill assign failed for event_id=%s: %s",
                    event.id,
                    exc,
                )

        with _actor_backfill_lock:
            _actor_backfill_state["progress"] = {
                "scanned": scanned,
                "updated": updated,
                "skipped": skipped,
                "errors": errors,
            }

        if not dry_run:
            try:
                db.commit()
                # Only advance the cursor after a successful commit so that a
                # commit failure does not silently skip events in the batch.
                last_id = batch_last_id
            except Exception as exc:
                errors += 1
                logger.warning("actor backfill commit failed: %s", exc)
                db.rollback()
        else:
            last_id = batch_last_id

        if scanned and scanned % _ACTOR_BACKFILL_PROGRESS_LOG_EVERY < _ACTOR_BACKFILL_BATCH_SIZE:
            logger.info(
                "Backfill actor display names: %d/? rows scanned, %d updated, %d skipped, %d errors (dry_run=%s)",
                scanned,
                updated,
                skipped,
                errors,
                dry_run,
            )

        if len(batch) < _ACTOR_BACKFILL_BATCH_SIZE:
            # Last page of this pass — advance to next
            pass_idx += 1
            last_id = None

        if _ACTOR_BACKFILL_BATCH_SLEEP_MS > 0:
            sleep(_ACTOR_BACKFILL_BATCH_SLEEP_MS / 1000.0)

    logger.info(
        "Backfill actor display names complete: scanned=%d updated=%d skipped=%d errors=%d dry_run=%s",
        scanned,
        updated,
        skipped,
        errors,
        dry_run,
    )
    return {
        "scanned": scanned,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "dry_run": dry_run,
    }


# ──────────────────────────────────────────────────────────────────────
# Normalize User: prefix in stored actor values.
# Events stored before the normalize_event() fix carry "User:u-xxxxx" or
# "User:sa-xxxxx" as the actor value.  This job strips the prefix so the
# same person is no longer stored as two distinct actors.
# ──────────────────────────────────────────────────────────────────────

_NORMALIZE_PREFIX_BATCH = 10_000
_NORMALIZE_PREFIX_SLEEP_MS = 10


def backfill_normalize_actor_prefixes(
    db: Session,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Strip spurious 'User:u-' and 'User:sa-' prefixes from the actor column.

    Processes in batches of 10K rows, committing after each batch.
    Events with 'User:NNNN' (numeric) are intentionally excluded — those
    need principalResourceId resolution, not simple prefix stripping.

    Returns {"updated": N, "batches": N, "dry_run": bool}.
    """
    is_postgres = db.get_bind().dialect.name == "postgresql"
    total = 0
    batches = 0

    while True:
        if is_postgres:
            db.execute(text(
                f"SET LOCAL statement_timeout = {_ACTOR_BACKFILL_STATEMENT_TIMEOUT_MS}"
            ))
            result = db.execute(text(
                "UPDATE audit_events"
                " SET actor = SUBSTRING(actor FROM 6),"
                "     actor_id = SUBSTRING(actor FROM 6)"
                " WHERE id IN ("
                "   SELECT id FROM audit_events"
                "   WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'"
                f"  LIMIT {_NORMALIZE_PREFIX_BATCH}"
                " )"
            ))
        else:
            result = db.execute(text(
                "UPDATE audit_events"
                " SET actor = SUBSTR(actor, 6),"
                "     actor_id = SUBSTR(actor, 6)"
                " WHERE rowid IN ("
                "   SELECT rowid FROM audit_events"
                "   WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'"
                f"  LIMIT {_NORMALIZE_PREFIX_BATCH}"
                " )"
            ))
        rows = result.rowcount
        if not dry_run:
            db.commit()
        else:
            db.rollback()
            # In dry_run mode, count via SELECT and stop after one iteration
            count_result = db.execute(text(
                "SELECT COUNT(*) FROM audit_events"
                " WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'"
            ))
            rows = count_result.scalar() or 0
            total = rows
            batches = (rows + _NORMALIZE_PREFIX_BATCH - 1) // _NORMALIZE_PREFIX_BATCH if rows else 0
            break

        total += rows
        batches += 1
        logger.info(
            "normalize-actor-prefixes: batch %d — %d rows updated (total=%d, dry_run=%s)",
            batches, rows, total, dry_run,
        )
        if rows < _NORMALIZE_PREFIX_BATCH:
            break
        if _NORMALIZE_PREFIX_SLEEP_MS > 0:
            sleep(_NORMALIZE_PREFIX_SLEEP_MS / 1000.0)

    logger.info(
        "normalize-actor-prefixes complete: updated=%d batches=%d dry_run=%s",
        total, batches, dry_run,
    )
    return {"updated": total, "batches": batches, "dry_run": dry_run}
