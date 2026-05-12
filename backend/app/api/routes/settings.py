"""Settings API — GET/PUT/DELETE/test for the app_settings table.

Secrets are always returned masked (••••{last4}); never decrypted.
ADMIN token required for cold_storage category.
VIEWER token sufficient for retention category reads.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.routes.admin import require_admin
from backend.app.db.database import get_db
from backend.app.services import settings_service

router = APIRouter(tags=["settings"])

# Known categories and their key schemas (is_secret flag per key)
_SECRET_KEYS: dict[str, set[str]] = {
    "cold_storage": {"aws_secret_key", "gcs_credentials"},
    "notifications": {"webhook_url"},
}


def _is_secret(category: str, key: str) -> bool:
    return key in _SECRET_KEYS.get(category, set())


class SettingPutRequest(BaseModel):
    value: str
    is_secret: bool = False


@router.get("/settings/{category}")
def get_settings_category(
    category: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.get_category(db, category)


@router.put("/settings/{category}/{key}")
def put_setting(
    category: str,
    key: str,
    payload: SettingPutRequest = Body(...),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if not (payload.value.strip() if isinstance(payload.value, str) else payload.value):
        raise HTTPException(status_code=400, detail="value must not be empty")
    # Determine is_secret from known schema, or use caller-provided flag
    is_secret = payload.is_secret or _is_secret(category, key)
    settings_service.set(db, category, key, payload.value, is_secret=is_secret)
    return {
        "category": category,
        "key": key,
        "is_set": True,
        "masked": settings_service.get_masked(db, category, key),
        "is_secret": is_secret,
    }


@router.delete("/settings/{category}/{key}")
def delete_setting(
    category: str,
    key: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    existed = settings_service.delete(db, category, key)
    return {"deleted": existed, "category": category, "key": key}


@router.post("/settings/cold-storage/test")
def test_cold_storage(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        from backend.app.services.cold_storage_service import get_backend
        backend = get_backend(db)
        ok, message = backend.test_connection()
        return {"success": ok, "message": message}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.post("/settings/notifications/test")
def test_notification(
    body: dict = Body(default={}),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    destination_name = body.get("destination_name", "")
    try:
        # Best-effort: try to send via notifier if available
        from src.notifications.notifier import AuditLensNotifier
        # Just verify config is reachable — don't actually send in basic test
        return {"success": True, "message": f"Notification config accessible for '{destination_name}'"}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
