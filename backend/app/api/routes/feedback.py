"""Public feedback submission endpoint.

POST /feedback  — unauthenticated, rate-limited (5/IP/hour, in-memory)
GET  /feedback  — viewer-protected, for future admin review
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.db.feedback import Feedback, FeedbackType
from backend.app.api.routes.patterns import _require_viewer

router = APIRouter(tags=["feedback"])

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter — approximate, per IP, 5 requests/hour max.
# Uses a sliding list of timestamps; old entries are pruned on each check.
# ---------------------------------------------------------------------------
_RATE_WINDOW_S = 3600
_RATE_MAX = 5
_rate_store: dict[str, list[float]] = {}


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
