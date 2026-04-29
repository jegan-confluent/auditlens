from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent


def _distinct(db: Session, column) -> list[str]:
    rows = db.scalars(select(column).distinct().order_by(column)).all()
    return [str(row) for row in rows if row not in (None, "")]


def get_filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "resource_types": _distinct(db, AuditEvent.resource_type),
        "action_categories": _distinct(db, AuditEvent.action_category),
        "results": _distinct(db, AuditEvent.result),
        "actors": _distinct(db, AuditEvent.actor),
    }
