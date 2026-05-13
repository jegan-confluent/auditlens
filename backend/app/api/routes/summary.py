from fastapi import APIRouter, Depends, Query, Request
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.limiter import limiter
from backend.app.db.database import get_db
from backend.app.schemas.response import MethodDistributionResponse, SummaryResponse
from backend.app.services.noise_service import get_method_distribution
from backend.app.services.summary_service import get_summary
from backend.app.api.routes.patterns import _require_viewer

router = APIRouter(tags=["summary"])


@router.get("/summary", response_model=SummaryResponse)
def summary(
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    mode: str = Query(default="decision"),
    resource_type: str | None = None,
    resource: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    include_noise: bool = Query(
        default=False,
        description="If true, attaches a noise_summary block sourced from audit_events_noise.",
    ),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> dict:
    try:
        return get_summary(
            db,
            time_window=time_window,
            mode=mode,
            resource_type=resource_type,
            resource=resource,
            action_category=action_category,
            actor=actor,
            result=result,
            signal_type=signal_type,
            hide_noise=hide_noise,
            impact_type=impact_type,
            change_type=change_type,
            include_noise=include_noise,
            noise_retention_days=get_settings().noise_retention_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/summary/methods", response_model=MethodDistributionResponse)
@limiter.limit("10/minute")
def summary_methods(request: Request, db: Session = Depends(get_db), _auth: None = Depends(_require_viewer)) -> dict:
    """Unified method distribution across audit_events and audit_events_noise.

    The two physical tables are queried independently and merged client-side
    (in the service layer) so a customer asking 'what method volume did I
    have last week' sees a single ranked list — including the noise methods
    that the show_noise=false default hides on /events. Cached for 60 s
    keyed by the bound engine.
    """
    return get_method_distribution(db)
