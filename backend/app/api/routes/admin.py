from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import get_db
from backend.app.services.event_service import cleanup_retention

router = APIRouter(tags=["admin"])


@router.post("/admin/retention/cleanup")
def retention_cleanup(
    dry_run: bool = Query(default=True),
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> dict:
    days = retention_days or get_settings().event_retention_days
    return cleanup_retention(db, days, dry_run=dry_run)
