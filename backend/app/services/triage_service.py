from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent, AuditEventTriage
from src.product.triage_store import DEFAULT_TRIAGE, get_triage as get_file_triage

ALLOWED_TRIAGE_STATUSES = {"open", "acknowledged", "approved", "investigating", "resolved", "false_positive"}
TRIAGE_STATUS_ALIASES = {
    "unreviewed": "open",
    "ignored": "false_positive",
}


def normalize_triage_status(status: str) -> str:
    value = (status or "").strip().lower()
    if not value:
        raise ValueError(f"triage_status must be one of: {', '.join(sorted(ALLOWED_TRIAGE_STATUSES | set(TRIAGE_STATUS_ALIASES)))}")
    canonical = TRIAGE_STATUS_ALIASES.get(value, value)
    if canonical not in ALLOWED_TRIAGE_STATUSES:
        raise ValueError(f"triage_status must be one of: {', '.join(sorted(ALLOWED_TRIAGE_STATUSES | set(TRIAGE_STATUS_ALIASES)))}")
    return canonical


def _snapshot_from_record(record: AuditEventTriage | None, *, fallback_key: str | None = None) -> dict[str, Any]:
    if record is None:
        return {**DEFAULT_TRIAGE, **(get_file_triage(fallback_key) if fallback_key is not None else {})}
    timestamp = record.reviewed_at or record.resolved_at or record.updated_at or record.created_at
    return {
        "triage_status": record.triage_status or DEFAULT_TRIAGE["triage_status"],
        "triage_actor": record.triage_actor,
        "triage_timestamp": timestamp.isoformat() if timestamp is not None else None,
        "triage_note": record.triage_note,
        "triage_source": record.triage_source,
    }


def get_triage_record(db: Session, event_fingerprint: str) -> AuditEventTriage | None:
    return db.scalar(select(AuditEventTriage).where(AuditEventTriage.event_fingerprint == event_fingerprint))


def get_triage_snapshot(db: Session, event_fingerprint: str) -> dict[str, Any]:
    record = get_triage_record(db, event_fingerprint)
    return _snapshot_from_record(record, fallback_key=event_fingerprint)


def get_triage_snapshots(db: Session, event_fingerprints: Iterable[str]) -> dict[str, dict[str, Any]]:
    fingerprints = [fingerprint for fingerprint in event_fingerprints if fingerprint]
    if not fingerprints:
        return {}
    records = db.scalars(select(AuditEventTriage).where(AuditEventTriage.event_fingerprint.in_(fingerprints))).all()
    snapshots = {record.event_fingerprint: _snapshot_from_record(record) for record in records}
    for fingerprint in fingerprints:
        snapshots.setdefault(fingerprint, _snapshot_from_record(None, fallback_key=fingerprint))
    return snapshots


def existing_event_fingerprints(db: Session, event_fingerprints: Iterable[str]) -> set[str]:
    fingerprints = [fingerprint for fingerprint in event_fingerprints if fingerprint]
    if not fingerprints:
        return set()
    rows = db.scalars(select(AuditEvent.event_fingerprint).where(AuditEvent.event_fingerprint.in_(fingerprints))).all()
    return {str(row) for row in rows if row}


def attach_triage_snapshots(db: Session, events: Iterable[AuditEvent]) -> None:
    items = list(events)
    if not items:
        return
    snapshots = get_triage_snapshots(db, [event.event_fingerprint for event in items])
    for event in items:
        setattr(event, "_triage_cache", snapshots.get(event.event_fingerprint, DEFAULT_TRIAGE))


def upsert_triage(
    db: Session,
    event_fingerprint: str,
    triage_status: str,
    *,
    actor: str | None = None,
    note: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    canonical_status = normalize_triage_status(triage_status)
    now = datetime.now(timezone.utc)
    record = get_triage_record(db, event_fingerprint)
    if record is None:
        record = AuditEventTriage(event_fingerprint=event_fingerprint)
        db.add(record)
        record.created_at = now
    record.triage_status = canonical_status
    record.triage_actor = actor or "api"
    record.triage_note = note
    record.triage_source = source
    record.updated_at = now
    if canonical_status in {"open"}:
        record.reviewed_at = None
        record.resolved_at = None
    else:
        record.reviewed_at = now
        record.resolved_at = now if canonical_status == "resolved" else None
    db.commit()
    db.refresh(record)
    return _snapshot_from_record(record)


def import_triage_snapshot(
    db: Session,
    *,
    event_fingerprint: str,
    triage_status: str,
    triage_actor: str | None = None,
    triage_note: str | None = None,
    triage_timestamp: str | None = None,
    triage_source: str = "file_import",
    force: bool = False,
) -> tuple[bool, bool]:
    existing = get_triage_record(db, event_fingerprint)
    if existing is not None and not force:
        return False, False
    canonical_status = normalize_triage_status(triage_status)
    now = datetime.now(timezone.utc)
    reviewed_at = None
    resolved_at = None
    if triage_timestamp:
        try:
            parsed = datetime.fromisoformat(triage_timestamp.replace("Z", "+00:00"))
            reviewed_at = parsed if canonical_status != "open" else None
            resolved_at = parsed if canonical_status == "resolved" else None
        except ValueError:
            reviewed_at = now if canonical_status != "open" else None
            resolved_at = now if canonical_status == "resolved" else None
    else:
        reviewed_at = now if canonical_status != "open" else None
        resolved_at = now if canonical_status == "resolved" else None

    if existing is None:
        record = AuditEventTriage(
            event_fingerprint=event_fingerprint,
            triage_status=canonical_status,
            triage_actor=triage_actor or "file_import",
            triage_note=triage_note,
            triage_source=triage_source,
            created_at=now,
            updated_at=now,
            reviewed_at=reviewed_at,
            resolved_at=resolved_at,
        )
        db.add(record)
        db.commit()
        return True, False

    existing.triage_status = canonical_status
    existing.triage_actor = triage_actor or existing.triage_actor or "file_import"
    existing.triage_note = triage_note if triage_note is not None else existing.triage_note
    existing.triage_source = triage_source
    existing.updated_at = now
    existing.reviewed_at = reviewed_at
    existing.resolved_at = resolved_at
    db.commit()
    return False, True
