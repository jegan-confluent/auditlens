from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.event import AuditEventDetailOut
from backend.app.schemas.response import EventListResponse
from backend.app.services.event_service import get_event, list_deletions, list_events_result, list_failures
from backend.app.services.triage_service import upsert_triage
from src.product.auth import AuthConfig, Authenticator, Role

# /events list + detail are the most expensive routes; cap them tighter than
# the global default. The limiter instance is shared across routes via
# ``backend.app.core.limiter``.
from backend.app.core.limiter import limiter

router = APIRouter(tags=["events"])


class _RedactedEventView:
    __slots__ = ("_event",)

    def __init__(self, event: Any):
        self._event = event

    def __getattr__(self, item: str):
        if item == "raw_payload_json":
            return None
        return getattr(self._event, item)


def _can_view_raw_payload(headers) -> bool:
    try:
        auth_config = AuthConfig.from_env()
    except Exception:
        return False
    if not auth_config.enabled:
        return False
    result = Authenticator(auth_config).authenticate(headers)
    return bool(result.ok and result.actor and result.actor.role == Role.ADMIN)


class TriageUpdate(BaseModel):
    triage_status: str
    triage_note: str | None = None
    triage_actor: str | None = None


@router.get("/events", response_model=EventListResponse)
@limiter.limit("20/minute")
def events(
    request: Request,
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    mode: str = Query(default="decision"),
    resource_type: str | None = None,
    resource: str | None = None,
    cluster_name: str | None = None,
    environment_name: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    is_denied: bool | None = None,
    signal_type: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    debug: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, description="Opaque keyset cursor; pass back the next_cursor from the previous response"),
    db: Session = Depends(get_db),
) -> EventListResponse:
    try:
        result_set = list_events_result(
            db,
            time_window=time_window,
            mode=mode,
            resource_type=resource_type,
            resource=resource,
            cluster_name=cluster_name,
            environment_name=environment_name,
            action_category=action_category,
            actor=actor,
            result=result,
            is_denied=is_denied,
            signal_type=signal_type,
            hide_noise=hide_noise,
            impact_type=impact_type,
            change_type=change_type,
            debug=debug,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EventListResponse(
        items=result_set.items,
        limit=limit,
        offset=offset,
        total=result_set.total,
        scanned_events=result_set.scanned_events,
        signal_filter_applied=result_set.signal_filter_applied,
        hide_noise_applied=result_set.hide_noise_applied,
        result_limit_reached=result_set.result_limit_reached,
        next_cursor=result_set.next_cursor,
        debug=result_set.debug,
    )


@router.get("/events/{event_id}", response_model=AuditEventDetailOut)
@limiter.limit("20/minute")
def event_detail(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _can_view_raw_payload(request.headers):
        return _RedactedEventView(event)
    return event


@router.post("/events/{event_id}/triage", response_model=AuditEventDetailOut)
def update_event_triage(
    event_id: int,
    payload: TriageUpdate,
    db: Session = Depends(get_db),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
):
    event = get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        triage = upsert_triage(
            db,
            event.event_fingerprint,
            payload.triage_status,
            actor=payload.triage_actor or x_actor,
            note=payload.triage_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    setattr(event, "_triage_cache", triage)
    return event


@router.get("/failures", response_model=EventListResponse)
def failures(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> EventListResponse:
    items, total = list_failures(db, limit=limit, offset=offset)
    return EventListResponse(items=items, limit=limit, offset=offset, total=total)


@router.get("/deletions", response_model=EventListResponse)
def deletions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> EventListResponse:
    items, total = list_deletions(db, limit=limit, offset=offset)
    return EventListResponse(items=items, limit=limit, offset=offset, total=total)
