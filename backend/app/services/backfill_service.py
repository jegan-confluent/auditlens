import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from src.product.source_enrichment import extract_source_info

logger = logging.getLogger("auditlens.backend.backfill")


@dataclass
class BackfillResult:
    scanned: int = 0
    updated: int = 0
    invalid_json: int = 0
    dry_run: bool = True
    force: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "updated": self.updated,
            "invalid_json": self.invalid_json,
            "dry_run": self.dry_run,
            "force": self.force,
        }


SOURCE_FIELDS = ("source_ip", "source_context", "client_id", "connection_id", "request_id", "environment_id", "flink_region", "network_id")
FIELD_ATTRS = {
    "source_ip": "source_ip",
    "source_context": "_source_context",
    "client_id": "_client_id",
    "connection_id": "_connection_id",
    "request_id": "_request_id",
    "environment_id": "environment_id",
    "flink_region": "flink_region",
    "network_id": "network_id",
}


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
    except Exception:
        return False


def _top_level_keys(payload: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in payload.keys())


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


def _backfill_decision(
    event: AuditEvent,
    payload: dict[str, Any],
    *,
    force: bool,
) -> dict[str, Any]:
    has_raw_payload = bool(event.raw_payload_json)
    if not _has_column(event, "source_ip"):
        return {
            "id": event.id,
            "has_raw_payload_json": has_raw_payload,
            "has_data_json_column": _has_column(event, "data_json"),
            "raw_payload_top_level_keys": _top_level_keys(payload) if has_raw_payload else [],
            "extracted_source_ip": "",
            "extracted_source_context": "",
            "update_reason": "source_ip_column_missing",
            "would_update": False,
        }
    source_context_missing = getattr(event, FIELD_ATTRS["source_context"], None) in (None, "")
    current_source_ip = getattr(event, FIELD_ATTRS["source_ip"], None)
    if not has_raw_payload:
        return {
            "id": event.id,
            "has_raw_payload_json": False,
            "has_data_json_column": _has_column(event, "data_json"),
            "raw_payload_top_level_keys": [],
            "extracted_source_ip": "",
            "extracted_source_context": "",
            "update_reason": "no_raw_payload",
            "would_update": False,
        }

    if current_source_ip not in (None, "") and not force:
        extracted_source_info = extract_source_info(payload, event)
        return {
            "id": event.id,
            "has_raw_payload_json": True,
            "has_data_json_column": _has_column(event, "data_json"),
            "raw_payload_top_level_keys": _top_level_keys(payload),
            "extracted_source_ip": _source_ip_from_payload(payload, event),
            "extracted_source_context": extracted_source_info.get("source_context") or "",
            "update_reason": "already_has_source_ip",
            "would_update": False,
        }

    extracted_source_ip = _source_ip_from_payload(payload, event)
    extracted_source_info = extract_source_info(payload, event)
    extracted_source_context = extracted_source_info.get("source_context") or ""
    if not extracted_source_ip:
        return {
            "id": event.id,
            "has_raw_payload_json": True,
            "has_data_json_column": _has_column(event, "data_json"),
            "raw_payload_top_level_keys": _top_level_keys(payload),
            "extracted_source_ip": "",
            "extracted_source_context": extracted_source_context,
            "update_reason": "no_source_found",
            "would_update": False,
        }
    if source_context_missing or force:
        return {
            "id": event.id,
            "has_raw_payload_json": True,
            "has_data_json_column": _has_column(event, "data_json"),
            "raw_payload_top_level_keys": _top_level_keys(payload),
            "extracted_source_ip": extracted_source_ip,
            "extracted_source_context": extracted_source_context,
            "update_reason": "would_update",
            "would_update": True,
        }
    return {
        "id": event.id,
        "has_raw_payload_json": True,
        "has_data_json_column": _has_column(event, "data_json"),
        "raw_payload_top_level_keys": _top_level_keys(payload),
        "extracted_source_ip": extracted_source_ip,
        "extracted_source_context": extracted_source_context,
        "update_reason": "would_update",
        "would_update": True,
    }


def _needs_source_backfill(event: AuditEvent, *, force: bool) -> bool:
    if force:
        return True
    return any(getattr(event, FIELD_ATTRS[field]) in (None, "") for field in SOURCE_FIELDS)


def backfill_source_fields_from_raw_payload(
    db: Session,
    *,
    dry_run: bool = True,
    limit: int = 1000,
    force: bool = False,
    target_id: int | None = None,
    debug_sample: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 10000))
    query = select(AuditEvent).order_by(AuditEvent.id.asc(), AuditEvent.timestamp.asc()).limit(limit)
    if target_id is not None:
        query = query.where(AuditEvent.id == target_id).limit(1)
    if not force:
        query = query.where(
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
    result = BackfillResult(dry_run=dry_run, force=force)
    if target_id is None and not force:
        query = query.where(
            or_(
                AuditEvent.raw_payload_json.contains('"clientIp"'),
                AuditEvent.raw_payload_json.contains('"client_ip"'),
                AuditEvent.raw_payload_json.contains('"requestMetadata"'),
                AuditEvent.raw_payload_json.contains('"clientAddress"'),
                AuditEvent.raw_payload_json.contains('"data_json"'),
            )
        )
    for event in db.scalars(query).all():
        result.scanned += 1
        try:
            payload = json.loads(event.raw_payload_json) if event.raw_payload_json else {}
        except json.JSONDecodeError:
            result.invalid_json += 1
            continue
        source_info = extract_source_info(payload, event)
        source_ip = _source_ip_from_payload(payload, event) or source_info.get("source_ip")
        changed = False
        for field in SOURCE_FIELDS:
            attr = FIELD_ATTRS[field]
            current = getattr(event, attr)
            next_value = source_ip if field == "source_ip" else source_info.get(field)
            if next_value in (None, ""):
                continue
            if force or current in (None, ""):
                changed = True
                if not dry_run:
                    setattr(event, field, next_value)
        if changed:
            result.updated += 1
        if debug_sample > 0:
            decision = _backfill_decision(event, payload, force=force)
            print(
                "row "
                f"id={decision['id']} "
                f"has_raw_payload_json={'yes' if decision['has_raw_payload_json'] else 'no'} "
                f"has_data_json_column={'yes' if decision['has_data_json_column'] else 'no'} "
                f"raw_payload_top_level_keys={','.join(decision['raw_payload_top_level_keys']) or '-'} "
                f"extracted_source_ip={decision['extracted_source_ip'] or '-'} "
                f"extracted_source_context={decision['extracted_source_context'] or '-'} "
                f"update_reason={decision['update_reason']}"
            )
            debug_sample -= 1
    if not dry_run:
        db.commit()
    logger.info("source field backfill complete scanned=%s updated=%s invalid_json=%s dry_run=%s force=%s", result.scanned, result.updated, result.invalid_json, dry_run, force)
    return result.as_dict()
