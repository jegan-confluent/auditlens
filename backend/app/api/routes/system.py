from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.response import SystemStatusResponse
from backend.app.services.system_service import get_system_status

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)) -> dict:
    return get_system_status(db)
