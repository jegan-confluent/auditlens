from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent


def _group_counts(db: Session, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {str(key): int(count) for key, count in rows if key is not None}


def get_summary(db: Session) -> dict:
    total = db.scalar(select(func.count(AuditEvent.id))) or 0
    failures = db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.is_failure.is_(True))) or 0
    denials = db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.is_denied.is_(True))) or 0
    return {
        "total_events": int(total),
        "failures": int(failures),
        "denials": int(denials),
        "by_action_category": _group_counts(db, AuditEvent.action_category),
        "by_resource_type": _group_counts(db, AuditEvent.resource_type),
        "by_result": _group_counts(db, AuditEvent.result),
    }
