from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.event import AuditEventDetail
from backend.app.schemas.response import EventListResponse
from backend.app.services.event_service import get_event, list_deletions, list_events, list_failures

router = APIRouter(tags=["events"])


@router.get("/events", response_model=EventListResponse)
def events(
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    resource_type: str | None = None,
    resource: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> EventListResponse:
    items, total = list_events(
        db,
        time_window=time_window,
        resource_type=resource_type,
        resource=resource,
        action_category=action_category,
        actor=actor,
        result=result,
        limit=limit,
        offset=offset,
    )
    return EventListResponse(items=items, limit=limit, offset=offset, total=total)


@router.get("/events/{event_id}", response_model=AuditEventDetail)
def event_detail(event_id: int, db: Session = Depends(get_db)):
    event = get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
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
