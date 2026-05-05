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


def _needs_source_backfill(event: AuditEvent, *, force: bool) -> bool:
    if force:
        return True
    return any(getattr(event, FIELD_ATTRS[field]) in (None, "") for field in SOURCE_FIELDS)


def backfill_source_fields_from_raw_payload(db: Session, *, dry_run: bool = True, limit: int = 1000, force: bool = False) -> dict[str, Any]:
    limit = max(1, min(int(limit), 10000))
    query = select(AuditEvent).order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(limit)
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
    for event in db.scalars(query).all():
        result.scanned += 1
        try:
            payload = json.loads(event.raw_payload_json) if event.raw_payload_json else {}
        except json.JSONDecodeError:
            result.invalid_json += 1
            continue
        source_info = extract_source_info(payload, event)
        changed = False
        for field in SOURCE_FIELDS:
            attr = FIELD_ATTRS[field]
            current = getattr(event, attr)
            next_value = source_info.get(field)
            if next_value in (None, ""):
                continue
            if force or current in (None, ""):
                changed = True
                if not dry_run:
                    setattr(event, field, next_value)
        if changed:
            result.updated += 1
    if not dry_run:
        db.commit()
    logger.info("source field backfill complete scanned=%s updated=%s invalid_json=%s dry_run=%s force=%s", result.scanned, result.updated, result.invalid_json, dry_run, force)
    return result.as_dict()
