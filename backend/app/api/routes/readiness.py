from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.database import check_db_health_session, get_db
from backend.app.services.system_service import get_forwarder_status, get_storage_usage

router = APIRouter(tags=["runtime"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    try:
        db_health = check_db_health_session(db)
        storage = get_storage_usage(db)
        ingestion = get_forwarder_status()
        return {
            "status": "ready",
            "database_mode": get_settings().database_mode,
            "db": db_health,
            "storage_usage": storage,
            "ingestion": {
                "consumer_state": ingestion["consumer_state"],
                "db_writer_enabled": ingestion["db_writer_enabled"],
                "db_writer_state": ingestion["db_writer_state"],
                "db_last_successful_write": ingestion["db_last_successful_write"],
                "db_write_error_total": ingestion["db_write_error_total"],
                "last_error": ingestion["last_error"],
            },
        }
    except Exception as exc:
        return {"status": "not_ready", "database_mode": get_settings().database_mode, "db": {"can_connect": False, "can_query": False, "error": str(exc)}}
