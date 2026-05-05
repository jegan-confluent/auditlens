from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health_session, get_db
from backend.app.services.system_service import get_forwarder_status, get_storage_usage

router = APIRouter(tags=["runtime"])


def _is_forwarder_ready(ingestion: dict) -> bool:
    consumer_ready = ingestion.get("consumer_state") in {"connected", "idle"}
    writer_ready = ingestion.get("db_writer_enabled") is True and ingestion.get("db_writer_state") == "connected"
    return consumer_ready and writer_ready


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db_health = check_db_health_session(db)
        storage = get_storage_usage(db)
        is_ready = bool(db_health.get("can_connect") and db_health.get("can_query"))
        payload = {
            "status": "ready" if is_ready else "not_ready",
            "database_mode": get_settings().database_mode,
            "db": db_health,
            "storage_usage": storage,
            "components": {
                "api": "ready",
                "db": "ready" if is_ready else "not_ready",
            },
        }
        return JSONResponse(status_code=200 if is_ready else 503, content=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database_mode": get_settings().database_mode,
                "db": {"can_connect": False, "can_query": False, "error": str(exc)},
                "components": {"api": "ready", "db": "not_ready"},
            },
        )


@router.get("/pipeline/ready")
@router.get("/ingestion/ready")
def pipeline_ready(db: Session = Depends(get_db)):
    try:
        db_health = check_db_health_session(db)
        ingestion = get_forwarder_status()
        db_ready = bool(db_health.get("can_connect") and db_health.get("can_query"))
        ingestion_ready = _is_forwarder_ready(ingestion)
        is_ready = db_ready and ingestion_ready
        payload = {
            "status": "ready" if is_ready else "degraded",
            "database_mode": get_settings().database_mode,
            "db": db_health,
            "ingestion": {
                "consumer_state": ingestion["consumer_state"],
                "db_writer_enabled": ingestion["db_writer_enabled"],
                "db_writer_state": ingestion["db_writer_state"],
                "db_last_successful_write": ingestion["db_last_successful_write"],
                "db_write_error_total": ingestion["db_write_error_total"],
                "last_error": ingestion["last_error"],
            },
            "components": {
                "api": "ready",
                "db": "ready" if db_ready else "not_ready",
                "forwarder": "ready" if ingestion.get("consumer_state") in {"connected", "idle"} else "degraded",
                "db_writer": "ready" if ingestion.get("db_writer_enabled") is True and ingestion.get("db_writer_state") == "connected" else "degraded",
            },
        }
        return JSONResponse(status_code=200 if is_ready else 503, content=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database_mode": get_settings().database_mode,
                "db": {"can_connect": False, "can_query": False, "error": str(exc)},
                "components": {"api": "ready", "db": "not_ready", "forwarder": "degraded", "db_writer": "degraded"},
            },
        )
