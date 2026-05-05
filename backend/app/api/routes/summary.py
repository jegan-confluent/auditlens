from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.response import SummaryResponse
from backend.app.services.summary_service import get_summary

router = APIRouter(tags=["summary"])


@router.get("/summary", response_model=SummaryResponse)
def summary(
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    resource_type: str | None = None,
    resource: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    try:
        return get_summary(
            db,
            time_window=time_window,
            resource_type=resource_type,
            resource=resource,
            action_category=action_category,
            actor=actor,
            result=result,
            signal_type=signal_type,
            hide_noise=hide_noise,
            impact_type=impact_type,
            change_type=change_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
