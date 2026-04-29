from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.response import SummaryResponse
from backend.app.services.summary_service import get_summary

router = APIRouter(tags=["summary"])


@router.get("/summary", response_model=SummaryResponse)
def summary(db: Session = Depends(get_db)) -> dict:
    return get_summary(db)
