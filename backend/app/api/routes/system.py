from typing import Any

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import get_db
from backend.app.schemas.response import SystemStatusResponse
from backend.app.services.system_service import get_system_status

router = APIRouter(tags=["system"])


# Browser hits the backend (CORS-allowed) instead of the forwarder's port
# 8003 directly. The backend forwards the call inside Docker.
_FORWARDER_REQUEST_TIMEOUT_SECONDS = 5.0
_VACUUM_REQUEST_TIMEOUT_SECONDS = 30.0


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)) -> dict:
    return get_system_status(db)


@router.get("/system/forwarder-health")
def forwarder_health() -> JSONResponse:
    settings = get_settings()
    try:
        response = httpx.get(settings.forwarder_health_url, timeout=_FORWARDER_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except httpx.TimeoutException:
        return JSONResponse(status_code=200, content={"status": "unknown", "error": "timeout"})
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=200, content={"status": "unknown", "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=200, content={"status": "unknown", "error": f"unexpected: {exc}"})
    return JSONResponse(status_code=200, content=payload)


@router.post("/system/vacuum")
def vacuum_forwarder_db() -> JSONResponse:
    settings = get_settings()
    # FORWARDER_HEALTH_URL ends in /health; rewrite to /admin/vacuum.
    base_url = settings.forwarder_health_url.rsplit("/", 1)[0] if settings.forwarder_health_url else ""
    vacuum_url = f"{base_url}/admin/vacuum" if base_url else ""
    if not vacuum_url:
        return JSONResponse(status_code=503, content={"status": "failure", "error": "forwarder url not configured"})
    try:
        response = httpx.post(vacuum_url, timeout=_VACUUM_REQUEST_TIMEOUT_SECONDS)
        body: dict[str, Any] = response.json() if response.content else {}
        return JSONResponse(status_code=response.status_code, content=body)
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"status": "failure", "error": "forwarder timeout"})
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=502, content={"status": "failure", "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "failure", "error": f"unexpected: {exc}"})
