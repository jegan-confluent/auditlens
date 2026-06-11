"""POST /ai/summary, GET /ai/summary/latest, GET /ai/summary/health.

Thin router. All heavy lifting (context build, Claude call, cache,
failure handling) lives in ``backend.app.ai.summarizer``. The route
contract:

* Responses are always shaped like ``AuditSummary`` — the frontend
  reads ``status`` first and branches on disabled / error / ok.
* No 500s from this route. The summarizer never raises; if something
  catastrophic happens (e.g. someone deletes audit_events between
  request and response), we surface it as ``status="error"`` with the
  message in the body.
* Auth: ``_require_viewer`` — same gate every read endpoint uses.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.ai.schemas import AISummaryHealth, AuditSummary
from backend.app.ai.summarizer import AuditSummarizer, get_summarizer
from backend.app.api.routes.patterns import _require_viewer
from backend.app.core.limiter import limiter
from backend.app.db.database import get_db


logger = logging.getLogger("auditlens.backend.ai.routes")

router = APIRouter(prefix="/ai", tags=["ai_summary"])


class _SummaryRequest(BaseModel):
    window_hours: int = 24
    force: bool = False


def _coerce_window(value: int) -> int:
    """Clamp window_hours to [1, 168].

    The summarizer itself only uses the value as a SQL time-cutoff and a
    label, so clamping here keeps the prompt and the queries sane
    without leaking validation across modules.
    """
    if value < 1:
        return 1
    if value > 168:
        return 168
    return value


@router.post("/summary", response_model=AuditSummary)
@limiter.limit("12/minute")
async def post_summary(
    request: Request,
    body: _SummaryRequest | None = None,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> AuditSummary:
    """Generate (or fetch the cached) summary for the requested window.

    Accepts a JSON body — ``{"window_hours": 24, "force": false}`` —
    AND a ``?force=true`` query param so the dashboard's "Refresh"
    button can opt out of the cache without rebuilding the body. The
    query param wins when both are present.
    """
    payload = body or _SummaryRequest()
    window = _coerce_window(payload.window_hours)
    effective_force = bool(force) or bool(payload.force)
    summarizer: AuditSummarizer = get_summarizer()
    # Claude calls block the event loop; thread-pool keeps other
    # routes responsive while the summary call is in flight.
    return await run_in_threadpool(
        summarizer.summarize,
        db,
        window_hours=window,
        force=effective_force,
    )


@router.get("/summary/latest", response_model=AuditSummary | dict[str, Any])
@limiter.limit("60/minute")
def get_summary_latest(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    _auth: None = Depends(_require_viewer),
) -> AuditSummary | dict[str, Any]:
    """Return the cached summary without ever touching Claude.

    When nothing is cached, returns a 200 with ``{"status": "empty"}``
    instead of a 404 — the frontend already handles status-string
    branching, and a dedicated status code would force a second code
    path purely for "no data yet".
    """
    window = _coerce_window(window_hours)
    summarizer = get_summarizer()
    cached = summarizer.latest(window)
    if cached is not None:
        return cached
    return {
        "status": "empty",
        "message": "No summary has been generated for this window yet.",
        "window_hours": window,
    }


@router.get("/summary/health", response_model=AISummaryHealth)
@limiter.limit("60/minute")
def get_summary_health(
    request: Request,
    _auth: None = Depends(_require_viewer),
) -> dict[str, Any]:
    """Surface whether AI is enabled, configured, and (eventually) reachable.

    The frontend uses this to decide between rendering the AI panel or
    a muted "AI insights disabled — set CLAUDE_API_KEY to enable" banner.
    """
    return get_summarizer().health()
