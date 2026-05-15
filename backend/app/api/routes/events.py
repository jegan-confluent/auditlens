import csv
import io
import json
import logging
from typing import Any, Union

logger = logging.getLogger("auditlens.backend.events")

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.schemas.event import AuditEventDetailOut, AuditEventListOut, AuditNoiseListOut
from backend.app.schemas.response import EventListNoiseResponse, EventListResponse
from backend.app.services.event_service import EXPORT_MAX_ROWS, get_event, list_deletions, list_events_result, list_failures
from backend.app.services.noise_service import (
    NOISE_EVENTS_MAX_LIMIT,
    UNSUPPORTED_NOISE_FILTERS,
    list_noise_events,
)
from backend.app.services.triage_service import upsert_triage
from src.product.auth import AuthConfig, Authenticator, Role
from backend.app.api.routes.patterns import _require_responder, _require_viewer

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
    except Exception as exc:
        logger.warning("Auth config unavailable, denying raw payload access: %s", exc)
        return False
    if not auth_config.enabled:
        return True
    result = Authenticator(auth_config).authenticate(headers)
    return bool(result.ok and result.actor and result.actor.role == Role.ADMIN)


class TriageUpdate(BaseModel):
    triage_status: str
    triage_note: str | None = None
    triage_actor: str | None = None


@router.get(
    "/events",
    response_model=Union[EventListResponse, EventListNoiseResponse],
)
@limiter.limit("60/minute")
def events(
    request: Request,
    _auth: None = Depends(_require_viewer),
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    mode: str = Query(default="decision"),
    resource_type: str | None = None,
    resource: str | None = None,
    cluster_name: str | None = None,
    environment_name: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    is_denied: bool | None = None,
    signal_type: str | None = None,
    signal: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    debug: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, description="Opaque keyset cursor; pass back the next_cursor from the previous response"),
    show_noise: bool = Query(
        default=False,
        description="Read from audit_events_noise instead of audit_events. Restricted filters: only time_window/actor/action/limit/offset are honoured.",
    ),
    include_suppressed: bool = Query(
        default=False,
        description="When true, suppressed/expected patterns are included in decision mode results (for ops debugging).",
    ),
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Free-text search across event title, actor, resource name, and request ID.",
    ),
    production_hint: str | None = Query(
        default=None,
        description="Filter by production_hint value. Use 'production', 'non_production' (matches anything except production), or exact value.",
    ),
    plane: str | None = Query(
        default=None,
        description="Filter by plane type: 'control_plane' or 'data_plane'. Derived from the action method name.",
    ),
    db: Session = Depends(get_db),
):
    if show_noise:
        # Per the noise-table contract, only a small subset of filters
        # has a meaningful column on audit_events_noise. Reject the rest
        # at 400 so callers don't silently get an unfiltered result.
        rejected = []
        if signal_type:
            rejected.append("signal_type")
        if impact_type:
            rejected.append("impact_type")
        if change_type:
            rejected.append("change_type")
        if mode and mode != "decision":
            # `mode` is supplied with a default so we only reject when the
            # caller actively switched it; the default is harmless because
            # it doesn't apply to noise rows at all.
            rejected.append("mode")
        if resource_type:
            rejected.append("resource_type")
        if resource:
            rejected.append("resource")
        if is_denied is not None:
            rejected.append("is_denied")
        if result:
            rejected.append("result")
        if cluster_name:
            rejected.append("cluster_name")
        if environment_name:
            rejected.append("environment_name")
        if action_category:
            rejected.append("action_category")
        if hide_noise:
            rejected.append("hide_noise")
        if cursor:
            rejected.append("cursor")
        if rejected:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Filter {rejected[0]} is not supported for noise events. "
                    f"Supported filters with show_noise=true: time_window, actor, action, limit, offset. "
                    f"Rejected: {', '.join(sorted(set(rejected)))}."
                ),
            )
        capped_limit = min(int(limit), NOISE_EVENTS_MAX_LIMIT)
        try:
            noise_result = list_noise_events(
                db,
                time_window=time_window,
                actor=actor,
                action=action,
                limit=capped_limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return EventListNoiseResponse(
            items=[AuditNoiseListOut.model_validate(row) for row in noise_result.items],
            limit=capped_limit,
            offset=offset,
            total=noise_result.total,
        )

    effective_signal_type = signal_type or signal
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
            action=action,
            result=result,
            is_denied=is_denied,
            signal_type=effective_signal_type,
            hide_noise=hide_noise,
            impact_type=impact_type,
            change_type=change_type,
            debug=debug,
            limit=limit,
            offset=offset,
            cursor=cursor,
            include_suppressed=include_suppressed,
            q=q,
            production_hint=production_hint,
            plane=plane,
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


_EXPORT_COLUMNS = (
    "timestamp", "actor_display_name", "actor", "action", "resource_name",
    "resource_type", "result", "signal_type", "risk_level", "source_ip",
    "client_tool", "environment_id", "cluster_id", "event_title",
)


@router.get("/events/export")
@limiter.limit("10/minute")
def events_export(
    request: Request,
    _auth: None = Depends(_require_viewer),
    format: str = Query(default="json", pattern="^(csv|json)$"),
    limit: int = Query(default=1000, ge=1, le=10000),
    time_window: str | None = Query(default=None, pattern=r"^[1-9][0-9]*[mh]$"),
    mode: str = Query(default="decision"),
    resource_type: str | None = None,
    resource: str | None = None,
    cluster_name: str | None = None,
    environment_name: str | None = None,
    action_category: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    is_denied: bool | None = None,
    signal_type: str | None = None,
    signal: str | None = None,
    hide_noise: bool = False,
    impact_type: str | None = None,
    change_type: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    production_hint: str | None = None,
    plane: str | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    effective_signal = signal_type or signal
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
            action=action,
            result=result,
            is_denied=is_denied,
            signal_type=effective_signal,
            hide_noise=hide_noise,
            impact_type=impact_type,
            change_type=change_type,
            q=q,
            production_hint=production_hint,
            plane=plane,
            limit=limit,
            export_limit=EXPORT_MAX_ROWS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = result_set.items
    date_str = __import__("datetime").date.today().isoformat()

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_EXPORT_COLUMNS)
        for evt in items:
            row_data = AuditEventListOut.model_validate(evt).model_dump()
            writer.writerow([
                "" if row_data.get(col) is None else str(row_data[col])
                for col in _EXPORT_COLUMNS
            ])
        content = buf.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="auditlens-events-{date_str}.csv"'},
        )

    # JSON
    rows = []
    for evt in items:
        row_data = AuditEventListOut.model_validate(evt).model_dump()
        rows.append({col: row_data.get(col) for col in _EXPORT_COLUMNS})
    content = json.dumps(rows, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="auditlens-events-{date_str}.json"'},
    )


@router.get("/events/{event_id}", response_model=AuditEventDetailOut)
@limiter.limit("60/minute")
def event_detail(event_id: int, request: Request, db: Session = Depends(get_db), _auth: None = Depends(_require_viewer)):
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
    _auth: None = Depends(_require_responder),
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
    _auth: None = Depends(_require_viewer),
) -> EventListResponse:
    items, total = list_failures(db, limit=limit, offset=offset)
    return EventListResponse(items=items, limit=limit, offset=offset, total=total)


@router.get("/deletions", response_model=EventListResponse)
def deletions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> EventListResponse:
    items, total = list_deletions(db, limit=limit, offset=offset)
    return EventListResponse(items=items, limit=limit, offset=offset, total=total)
