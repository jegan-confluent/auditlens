from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent, ResourceCatalog
from src.product.resource_intelligence import extract_resource_context

logger = logging.getLogger("auditlens.backend.resource")


def _load_payload(event: AuditEvent | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload is not None:
        return payload
    if event is None:
        return {}
    try:
        return json.loads(event.raw_payload_json) if event.raw_payload_json else {}
    except json.JSONDecodeError:
        return {}


def _pick_seen_at(event: AuditEvent | None, seen_at: datetime | None = None) -> datetime:
    if seen_at is not None:
        return seen_at if seen_at.tzinfo is not None else seen_at.replace(tzinfo=timezone.utc)
    if event is not None and getattr(event, "timestamp", None) is not None:
        timestamp = event.timestamp
        return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _prefer(existing: Any, incoming: Any) -> Any:
    if incoming in (None, "", "-", "Unknown", "unknown", "Not provided by audit event"):
        return existing
    if existing in (None, "", "-", "Unknown", "unknown", "Not provided by audit event"):
        return incoming
    return existing


def upsert_resource_catalog(
    db: Session,
    event: AuditEvent | None = None,
    payload: dict[str, Any] | None = None,
    *,
    seen_at: datetime | None = None,
) -> ResourceCatalog | None:
    source_payload = _load_payload(event, payload)
    if not source_payload and event is None:
        return None
    try:
        context = extract_resource_context(source_payload, event)
        record = context.to_catalog_record(seen_at=_pick_seen_at(event, seen_at))
        if record["resource_type"] == "unknown" and record["resource_name"] in {"", "-"}:
            return None
        existing = db.scalar(select(ResourceCatalog).where(ResourceCatalog.resource_id == record["resource_id"]))
        if existing is None:
            existing = ResourceCatalog(**record)
            db.add(existing)
        else:
            existing.resource_type = _prefer(existing.resource_type, record["resource_type"])
            existing.resource_name = _prefer(existing.resource_name, record["resource_name"])
            existing.display_name = _prefer(existing.display_name, record["display_name"])
            existing.cluster_id = _prefer(existing.cluster_id, record["cluster_id"])
            existing.cluster_name = _prefer(existing.cluster_name, record["cluster_name"])
            existing.environment_id = _prefer(existing.environment_id, record["environment_id"])
            existing.environment_name = _prefer(existing.environment_name, record["environment_name"])
            existing.parent_resource = _prefer(existing.parent_resource, record["parent_resource"])
            existing.resource_scope = _prefer(existing.resource_scope, record["resource_scope"])
            existing.resource_criticality = _prefer(existing.resource_criticality, record["resource_criticality"])
            existing.blast_radius_hint = _prefer(existing.blast_radius_hint, record["blast_radius_hint"])
            existing.production_hint = _prefer(existing.production_hint, record["production_hint"])
            existing.source = _prefer(existing.source, record["source"])
            existing.metadata_json = record["metadata_json"]
            existing.last_seen_at = record["last_seen_at"]
            if existing.first_seen_at is None or record["first_seen_at"] < existing.first_seen_at:
                existing.first_seen_at = record["first_seen_at"]
        db.commit()
        db.refresh(existing)
        return existing
    except Exception as exc:  # pragma: no cover - best-effort enrichment
        db.rollback()
        logger.debug("resource catalog upsert failed: %s", exc)
        return None
