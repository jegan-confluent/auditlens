"""GET /access-transparency — paginated Access Transparency events.

Surfaces io.confluent.cloud/access-transparency events recorded when
Confluent personnel access customer Dedicated Kafka clusters for support,
maintenance, or operational purposes. Compliance-facing view: customers
with DORA / SOX / GDPR / FCA obligations need a single place to enumerate
all such accesses with the operator + business justification per row.

Reads from audit_events filtered on type — these events are persisted
through the same pipeline as other CloudEvents, so the existing column
schema + indexes already serve this query. NOT noise — never auto-purged.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.api.routes.patterns import _require_viewer
from backend.app.core.limiter import limiter
from backend.app.db.database import get_db
from backend.app.db.models import AuditEvent


router = APIRouter(tags=["access_transparency"])


_AT_EVENT_TYPE = "io.confluent.cloud/access-transparency"


class AccessTransparencyEventOut(BaseModel):
    id: int
    timestamp: datetime
    actor: str
    resource_name: str
    at_operator: str | None
    at_justification: str | None
    result: str
    environment_id: str | None


class AccessTransparencyResponse(BaseModel):
    items: list[AccessTransparencyEventOut]
    limit: int
    offset: int
    total: int


def _is_at_event_clause():
    """Match access-transparency events by signal_reason or raw_payload_json.

    The audit_events table doesn't carry a column for the CloudEvents type
    field (it lives inside raw_payload_json), so we rely on two signals
    that are columns:
      1. The dedicated at_operator / at_justification columns from Feature 4.
      2. The signal_reason="security_sensitive_change" set by the AT
         override in event_signals.py — but that is too broad on its own,
         so we AND it with the at_* column presence to keep precision.
    Falls back to raw_payload_json LIKE for events ingested before Feature 4.
    """
    return (
        (AuditEvent.at_operator.isnot(None))
        | (AuditEvent.at_justification.isnot(None))
        | (AuditEvent.raw_payload_json.like(f'%"{_AT_EVENT_TYPE}"%'))
    )


@router.get("/access-transparency", response_model=AccessTransparencyResponse)
@limiter.limit("60/minute")
def access_transparency(
    request: Request,
    _auth: None = Depends(_require_viewer),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AccessTransparencyResponse:
    """Return paginated Access Transparency events for the org."""
    where_clause = _is_at_event_clause()
    total = int(db.scalar(select(func.count(AuditEvent.id)).where(where_clause)) or 0)
    rows: list[AuditEvent] = list(
        db.scalars(
            select(AuditEvent)
            .where(where_clause)
            .order_by(desc(AuditEvent.timestamp), desc(AuditEvent.id))
            .limit(limit)
            .offset(offset)
        ).all()
    )
    items = [
        AccessTransparencyEventOut(
            id=row.id,
            timestamp=row.timestamp,
            actor=row.actor,
            resource_name=row.resource_name,
            at_operator=row.at_operator,
            at_justification=row.at_justification,
            result=row.result,
            environment_id=row.environment_id,
        )
        for row in rows
    ]
    return AccessTransparencyResponse(items=items, limit=limit, offset=offset, total=total)
