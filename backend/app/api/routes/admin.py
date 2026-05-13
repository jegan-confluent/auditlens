import time
import threading
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import get_db
from backend.app.services.backfill_service import (
    backfill_normalize_actor_prefixes,
    get_actor_backfill_status,
    start_actor_display_name_backfill,
)
from backend.app.services.event_service import cleanup_retention
from src.product.auth import AuthConfig, Authenticator, Role

router = APIRouter(tags=["admin"])

import os as _os
_auth_config_cache: tuple[float, AuthConfig, str] | None = None
_auth_config_lock = threading.Lock()
_AUTH_CONFIG_TTL = 60.0


def _get_auth_config() -> AuthConfig:
    global _auth_config_cache
    now = time.monotonic()
    # Include the key toggle in the cache key so env-var changes (e.g. in
    # tests via monkeypatch) invalidate the cache immediately.
    enabled_flag = _os.getenv("API_AUTH_ENABLED", "false")
    with _auth_config_lock:
        if (
            _auth_config_cache is not None
            and (now - _auth_config_cache[0]) < _AUTH_CONFIG_TTL
            and _auth_config_cache[2] == enabled_flag
        ):
            return _auth_config_cache[1]
    config = AuthConfig.from_env()
    with _auth_config_lock:
        _auth_config_cache = (now, config, enabled_flag)
    return config


def require_admin(request: Request) -> None:
    try:
        config = _get_auth_config()
        auth = Authenticator(config)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="API auth is enabled but not configured") from exc
    if not config.enabled:
        return
    result = auth.authenticate(request.headers)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.error)
    if result.actor and result.actor.role == Role.ADMIN:
        return
    raise HTTPException(status_code=403, detail="admin role required")


class ActorBackfillRequest(BaseModel):
    dry_run: bool = False


@router.post("/admin/retention/cleanup")
def retention_cleanup(
    dry_run: bool = Query(default=True),
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    days = retention_days or settings.event_retention_days
    return cleanup_retention(
        db,
        days,
        dry_run=dry_run,
        raw_payload_retention_days=settings.raw_payload_retention_days,
        noise_retention_days=settings.noise_retention_days,
    )


@router.post("/admin/backfill/actor-display-names")
def backfill_actor_display_names_endpoint(
    payload: ActorBackfillRequest = Body(default_factory=ActorBackfillRequest),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Re-resolve legacy 'Unknown user/SA/principal' rows. Async — returns
    immediately. Single-flight: a second POST while a job is running
    returns the in-flight job's state instead of starting a duplicate."""
    return start_actor_display_name_backfill(db.get_bind(), dry_run=payload.dry_run)


@router.get("/admin/backfill/actor-display-names/status")
def backfill_actor_display_names_status(
    _: None = Depends(require_admin),
) -> dict:
    return get_actor_backfill_status()


@router.post("/admin/backfill/normalize-actor-prefixes")
def normalize_actor_prefixes_endpoint(
    payload: ActorBackfillRequest = Body(default_factory=ActorBackfillRequest),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Strip spurious 'User:u-' / 'User:sa-' prefixes from the actor column.

    Synchronous — runs inline and returns when complete.  Batched at 10K rows
    to avoid table locks.  Safe to re-run: rows already normalized are
    unaffected (LIKE 'User:u-%' no longer matches)."""
    return backfill_normalize_actor_prefixes(db, dry_run=payload.dry_run)
