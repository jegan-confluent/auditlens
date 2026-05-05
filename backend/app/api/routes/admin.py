from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import get_db
from backend.app.services.event_service import cleanup_retention
from src.product.auth import AuthConfig, Authenticator, Role

router = APIRouter(tags=["admin"])


def require_admin(request: Request) -> None:
    try:
        auth = Authenticator(AuthConfig.from_env())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="API auth is enabled but not configured") from exc
    result = auth.authenticate(request.headers)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.role == Role.ADMIN:
        return
    raise HTTPException(status_code=403, detail="admin role required")


@router.post("/admin/retention/cleanup")
def retention_cleanup(
    dry_run: bool = Query(default=True),
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    days = retention_days or get_settings().event_retention_days
    return cleanup_retention(db, days, dry_run=dry_run)
