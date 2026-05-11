"""Pattern service — list, suppress, and manage recurring event patterns."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEventPattern

logger = logging.getLogger("auditlens.backend.patterns")

PATTERN_TIMEOUT_MS = 2000


def _set_timeout(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        try:
            db.execute(text(f"SET LOCAL statement_timeout = {PATTERN_TIMEOUT_MS}"))
        except Exception:
            pass


def list_patterns(
    db: Session,
    status: str | None = None,
    actor: str | None = None,
    limit: int = 50,
) -> dict:
    limit = min(max(limit, 1), 200)
    _set_timeout(db)
    conditions = []
    if status:
        conditions.append(AuditEventPattern.status == status)
    if actor:
        conditions.append(
            func.lower(AuditEventPattern.actor).like(f"%{actor.lower()}%")
        )
    query = select(AuditEventPattern)
    count_query = select(func.count(AuditEventPattern.id))
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)
    query = query.order_by(AuditEventPattern.occurrence_count.desc()).limit(limit)
    patterns = list(db.scalars(query).all())
    total = int(db.scalar(count_query) or 0)
    return {"patterns": [_to_dict(p) for p in patterns], "total": total}


def suppress_pattern(
    db: Session,
    pattern_id: int,
    duration_hours: int,
    reason: str,
    suppressed_by: str,
) -> AuditEventPattern | None:
    pattern = db.get(AuditEventPattern, pattern_id)
    if pattern is None:
        return None
    now = datetime.now(timezone.utc)
    pattern.status = "suppressed"
    pattern.suppressed_until = now + timedelta(hours=duration_hours) if duration_hours > 0 else None
    pattern.suppressed_by = suppressed_by
    pattern.suppression_reason = reason or None
    pattern.updated_at = now
    db.commit()
    db.refresh(pattern)
    return pattern


def mark_expected(
    db: Session,
    pattern_id: int,
    reason: str,
    marked_by: str,
) -> AuditEventPattern | None:
    pattern = db.get(AuditEventPattern, pattern_id)
    if pattern is None:
        return None
    now = datetime.now(timezone.utc)
    pattern.status = "expected"
    pattern.suppressed_until = None
    pattern.suppression_reason = reason or None
    pattern.suppressed_by = marked_by
    pattern.updated_at = now
    db.commit()
    db.refresh(pattern)
    return pattern


def reactivate_pattern(db: Session, pattern_id: int) -> AuditEventPattern | None:
    pattern = db.get(AuditEventPattern, pattern_id)
    if pattern is None:
        return None
    now = datetime.now(timezone.utc)
    pattern.status = "active"
    pattern.suppressed_until = None
    pattern.suppressed_by = None
    pattern.suppression_reason = None
    pattern.updated_at = now
    db.commit()
    db.refresh(pattern)
    return pattern


def get_suppressed_combos(db: Session) -> set[tuple[str, str, str]]:
    """Return (actor, action, resource_name) tuples for active suppressions."""
    _set_timeout(db)
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(
            AuditEventPattern.actor,
            AuditEventPattern.action,
            AuditEventPattern.resource_name,
        ).where(
            AuditEventPattern.status.in_(["suppressed", "expected"]),
            or_(
                AuditEventPattern.suppressed_until.is_(None),
                AuditEventPattern.suppressed_until > now,
            ),
        )
    ).all()
    return {(r.actor, r.action, _norm(r.resource_name)) for r in rows}


def _norm(value: str | None) -> str:
    """Normalize resource_name for matching: treat None and '-' as empty."""
    if not value or value == "-":
        return ""
    return value


def _to_dict(p: AuditEventPattern) -> dict:
    return {
        "id": p.id,
        "actor": p.actor,
        "action": p.action,
        "resource_name": p.resource_name,
        "occurrence_count": p.occurrence_count,
        "window_count": p.window_count,
        "first_seen_at": p.first_seen_at.isoformat() if p.first_seen_at else None,
        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
        "status": p.status,
        "suppressed_until": p.suppressed_until.isoformat() if p.suppressed_until else None,
        "suppressed_by": p.suppressed_by,
        "suppression_reason": p.suppression_reason,
    }
