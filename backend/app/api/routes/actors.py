"""Actor endpoints — IP baseline and narrative story."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.models import ActorIpBaseline, AuditEvent
from backend.app.api.routes.patterns import _require_viewer
from backend.app.services.narrative_service import get_actor_narrative

router = APIRouter(tags=["actors"])

# Display-name lookups walk audit_events ORDER BY timestamp DESC — bound
# the scan window (the IAM cache refreshes the name on every recent event
# anyway) and cap per-query budget so a missing actor can't tie up a worker.
_DISPLAY_NAME_LOOKBACK_DAYS = 7
_STMT_TIMEOUT_MS = 5_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/actors/{actor_id}/ip-baseline")
def get_actor_ip_baseline(actor_id: str, db: Session = Depends(get_db), _auth: None = Depends(_require_viewer)) -> dict:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {_STMT_TIMEOUT_MS}"))

    rows = (
        db.query(ActorIpBaseline)
        .filter(ActorIpBaseline.actor == actor_id)
        .order_by(ActorIpBaseline.last_seen_at.desc())
        .all()
    )

    now = _now()
    cutoff_24h_dt = now - timedelta(hours=24)
    display_lookback = now - timedelta(days=_DISPLAY_NAME_LOOKBACK_DAYS)

    new_ips_last_24h = sum(
        1 for r in rows
        if r.first_seen_at and r.first_seen_at >= cutoff_24h_dt
    )
    trusted_ips_configured = any(r.is_trusted for r in rows)

    # Resolve display name from the most recent audit event for this actor
    # within the bounded lookback window.
    actor_display_name: str | None = None
    recent = (
        db.query(AuditEvent.actor_display_name)
        .filter(AuditEvent.actor == actor_id)
        .filter(AuditEvent.actor_display_name.isnot(None))
        .filter(AuditEvent.timestamp >= display_lookback)
        .order_by(AuditEvent.timestamp.desc())
        .first()
    )
    if recent:
        actor_display_name = recent[0]

    ips = [
        {
            "source_ip": r.source_ip,
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "occurrence_count": r.occurrence_count,
            "cloud_provider": r.cloud_provider,
            "region": r.region,
            "is_trusted": bool(r.is_trusted),
            "is_new": r.first_seen_at >= cutoff_24h_dt if r.first_seen_at else False,
        }
        for r in rows
    ]

    return {
        "actor": actor_id,
        "actor_display_name": actor_display_name,
        "ips": ips,
        "total_ips": len(ips),
        "new_ips_last_24h": new_ips_last_24h,
        "trusted_ips_configured": trusted_ips_configured,
    }


@router.get("/actors/{actor_id}/narrative")
def get_actor_narrative_endpoint(
    actor_id: str,
    time_window: str = Query(default="24h"),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> dict:
    return get_actor_narrative(db, actor_id, time_window)
