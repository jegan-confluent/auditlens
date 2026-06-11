"""Feedback submission endpoint.

POST /feedback  — viewer-protected when API_AUTH_ENABLED=true (open in
                  local dev only), rate-limited (5/IP/hour, in-memory)
GET  /feedback  — viewer-protected, for future admin review
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.feedback import Feedback, FeedbackType
from backend.app.api.routes.patterns import _require_viewer

router = APIRouter(tags=["feedback"])

# ---------------------------------------------------------------------------
# In-memory rate limiter — per IP, 5 requests/hour max. TTLCache evicts
# IP keys automatically after _RATE_WINDOW_S seconds, so the dict can no
# longer grow unbounded with one entry per unique source IP. The per-IP
# list is still pruned on each check so an IP that hits within the
# window but below the limit doesn't keep stale timestamps until eviction.
# ---------------------------------------------------------------------------
_RATE_WINDOW_S = 3600
_RATE_MAX = 5
_rate_store: TTLCache = TTLCache(maxsize=10_000, ttl=_RATE_WINDOW_S)


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window_start = now - _RATE_WINDOW_S
    timestamps = [t for t in _rate_store.get(ip, []) if t > window_start]
    if len(timestamps) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Too many feedback submissions.")
    timestamps.append(now)
    _rate_store[ip] = timestamps


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FeedbackCreate(BaseModel):
    type: FeedbackType
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10, max_length=5000)
    email: EmailStr | None = None
    page_context: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: FeedbackType
    title: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def submit_feedback(
    payload: FeedbackCreate,
    request: Request,
    _auth: None = Depends(_require_viewer),
    db: Session = Depends(get_db),
) -> Any:
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    row = Feedback(
        type=payload.type,
        title=payload.title,
        description=payload.description,
        email=payload.email,
        page_context=payload.page_context,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/feedback", response_model=list[FeedbackOut])
def list_feedback(
    request: Request,
    _auth: None = Depends(_require_viewer),
    type: FeedbackType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Any:
    from sqlalchemy import select, desc
    stmt = select(Feedback).order_by(desc(Feedback.created_at)).limit(limit)
    if type is not None:
        stmt = stmt.where(Feedback.type == type)
    return list(db.scalars(stmt))
