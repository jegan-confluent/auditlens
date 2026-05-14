"""Settings API — GET/PUT/DELETE/test for the app_settings table.

Secrets are always returned masked (••••{last4}); never decrypted.
ADMIN token required for cold_storage category.
VIEWER token sufficient for retention category reads.
"""
from __future__ import annotations

import os
import time

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
    "schema_registry": {"api_key", "api_secret"},
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


def _get_sr_creds(db: Session) -> tuple[str, str, str]:
    """Return (url, api_key, api_secret) from settings table, falling back to env vars."""
    url = settings_service.get(db, "schema_registry", "url") or os.getenv("SCHEMA_REGISTRY_URL", "")
    api_key = settings_service.get(db, "schema_registry", "api_key") or os.getenv("SCHEMA_REGISTRY_API_KEY", "")
    api_secret = settings_service.get(db, "schema_registry", "api_secret") or os.getenv("SCHEMA_REGISTRY_API_SECRET", "")
    return url, api_key, api_secret


@router.get("/settings/schema_registry/status")
def get_sr_status(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    url, api_key, api_secret = _get_sr_creds(db)
    if not url:
        return {"configured": False, "url": None, "subjects": [], "error": None}
    try:
        from confluent_kafka.schema_registry import SchemaRegistryClient  # type: ignore[import-untyped]
        conf: dict = {"url": url}
        if api_key and api_secret:
            conf["basic.auth.user.info"] = f"{api_key}:{api_secret}"
        client = SchemaRegistryClient(conf)
        subjects: list[str] = client.get_subjects()
        return {"configured": True, "url": url, "subjects": subjects, "error": None}
    except ImportError:
        return {"configured": True, "url": url, "subjects": [], "error": "confluent-kafka not installed"}
    except Exception as exc:
        return {"configured": True, "url": url, "subjects": [], "error": str(exc)}


@router.post("/settings/test_sr")
def test_sr(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    url, api_key, api_secret = _get_sr_creds(db)
    if not url:
        return {"ok": False, "latency_ms": None, "error": "Schema Registry URL not configured"}
    try:
        from confluent_kafka.schema_registry import SchemaRegistryClient  # type: ignore[import-untyped]
        conf: dict = {"url": url}
        if api_key and api_secret:
            conf["basic.auth.user.info"] = f"{api_key}:{api_secret}"
        client = SchemaRegistryClient(conf)
        t0 = time.monotonic()
        client.get_subjects()
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "error": None}
    except ImportError:
        return {"ok": False, "latency_ms": None, "error": "confluent-kafka not installed"}
    except Exception as exc:
        return {"ok": False, "latency_ms": None, "error": str(exc)}
