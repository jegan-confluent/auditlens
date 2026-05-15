"""Pattern service — list, suppress, and manage recurring event patterns."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select, text, update
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent, AuditEventPattern

logger = logging.getLogger("auditlens.backend.patterns")

PATTERN_TIMEOUT_MS = 2000
PATTERN_STALE_HOURS = 24


def _set_timeout(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        try:
            db.execute(text(f"SET LOCAL statement_timeout = {PATTERN_TIMEOUT_MS}"))
        except Exception as exc:
            logger.debug("Could not set statement_timeout: %s", exc)


def _expire_stale_patterns(db: Session) -> None:
    """Mark active patterns as 'expired' if last_seen_at is > PATTERN_STALE_HOURS old.

    Lazy expiry — called at the start of list_patterns so stale rows are cleaned
    up on the first read after they go quiet, without any scheduled job.
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=PATTERN_STALE_HOURS)
    try:
        db.execute(
            update(AuditEventPattern)
            .where(
                AuditEventPattern.status == "active",
                AuditEventPattern.last_seen_at < stale_cutoff,
            )
            .values(status="expired", updated_at=datetime.now(timezone.utc))
        )
        db.commit()
    except Exception as exc:
        logger.warning("pattern expiry failed (non-fatal): %s", exc)
        db.rollback()


def list_patterns(
    db: Session,
    status: str | None = None,
    actor: str | None = None,
    limit: int = 50,
) -> dict:
    limit = min(max(limit, 1), 200)
    _expire_stale_patterns(db)
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
    enrichment = _enrich_actor_display_names(db, patterns)
    return {"patterns": [_to_dict(p, enrichment.get(p.actor)) for p in patterns], "total": total}


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


def _enrich_actor_display_names(
    db: Session,
    patterns: list[AuditEventPattern],
) -> dict[str, tuple[str | None, str | None]]:
    """Return {actor: (display_name, actor_type)} for each pattern actor that has enrichment."""
    if not patterns:
        return {}
    actor_values = list({p.actor for p in patterns if p.actor})
    if not actor_values:
        return {}
    try:
        # Restore a generous timeout before the per-actor loop.  list_patterns
        # set statement_timeout=2000 for its main queries; N per-actor LIMIT 1
        # queries each take <10ms but together can exceed 2s in the same
        # transaction window on a busy Postgres host.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = 10000"))

        # Single query for all actors — replaces N per-actor LIMIT 1 queries.
        # Ordered by actor then display-name priority; Python picks first row per actor.
        rows = db.execute(
            select(AuditEvent.actor, AuditEvent._actor_display_name, AuditEvent._actor_type)
            .where(
                AuditEvent.actor.in_(actor_values),
                AuditEvent._actor_display_name.isnot(None),
                AuditEvent._actor_display_name != "",
                AuditEvent._actor_display_name != AuditEvent.actor,
                AuditEvent._actor_display_name.notlike('{%'),
                AuditEvent._actor_display_name.notlike('________-____%'),
            )
            .order_by(
                AuditEvent.actor,
                case(
                    (
                        AuditEvent._actor_display_name.notlike('%@%') &
                        AuditEvent._actor_display_name.notlike('%-%-%-%-%'),
                        0,
                    ),
                    (AuditEvent._actor_display_name.like('%@%'), 1),
                    else_=2,
                ),
                AuditEvent.id.desc(),
            )
        ).all()
        result: dict[str, tuple[str | None, str | None]] = {}
        for row in rows:
            if row[0] not in result:
                result[row[0]] = (row[1], row[2])
        return result
    except Exception as exc:
        logger.warning("actor enrichment for patterns failed (non-fatal): %s", exc)
        return {}


def _to_dict(
    p: AuditEventPattern,
    enrichment: tuple[str | None, str | None] | None = None,
) -> dict:
    display_name, actor_type = enrichment if enrichment else (None, None)
    return {
        "id": p.id,
        "actor": p.actor,
        "actor_display_name": display_name,
        "actor_type": actor_type,
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
