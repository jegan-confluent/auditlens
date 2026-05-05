from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from src.product.event_normalization import canonical_resource_type


def _distinct(db: Session, column) -> list[str]:
    rows = db.scalars(select(column).distinct().order_by(column)).all()
    return [str(row) for row in rows if row not in (None, "")]


def _distinct_resource_types(db: Session) -> list[str]:
    values = {canonical_resource_type(row) for row in db.scalars(select(AuditEvent.resource_type).distinct()).all() if row not in (None, "")}
    expected = {"topic", "subject", "connector", "role_binding", "environment"}
    return sorted(values | expected)


def get_filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "resource_types": _distinct_resource_types(db),
        "action_categories": _distinct(db, AuditEvent.action_category),
        "results": _distinct(db, AuditEvent.result),
        "actors": _distinct(db, AuditEvent.actor),
    }
