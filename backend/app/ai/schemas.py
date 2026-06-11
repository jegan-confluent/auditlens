"""Pydantic response models for the AI summary endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SummaryStatus = Literal["ok", "disabled", "error"]
HealthBand = Literal["healthy", "elevated", "critical"]
Confidence = Literal["high", "medium", "low"]


class AuditSummary(BaseModel):
    """Container the API returns. Always shaped the same regardless of
    upstream status — frontend code only branches on ``status``."""

    status: SummaryStatus
    generated_at: datetime
    window_hours: int
    headline: str | None = None
    health: HealthBand | None = None
    summary: str | None = None
    anomalies: list[str] = Field(default_factory=list)
    top_risk: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    confidence: Confidence | None = None
    context_used: dict = Field(default_factory=dict)
    model_used: str | None = None
    latency_ms: int | None = None
    # Set when status != "ok"; carries the disabled/error explanation.
    message: str | None = None


class AISummaryHealth(BaseModel):
    """Result of ``GET /ai/summary/health`` — used by the frontend
    to decide whether to show the AI panel or the muted disabled banner."""

    enabled: bool
    configured: bool
    model: str
    cache_ttl_seconds: int
    # ``reachable`` is None when AI is disabled (we never tried) or when
    # the cheapest probe is not yet implemented. Today the route returns
    # None for both — the frontend treats None the same as True for the
    # "should I render the panel?" decision.
    reachable: bool | None = None
    message: str | None = None
