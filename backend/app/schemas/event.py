from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_fingerprint: str
    timestamp: datetime
    result: str
    actor: str
    action: str
    normalized_action: str
    action_category: str
    resource_type: str
    resource_name: str
    resource_display: str
    cluster_id: str | None = None
    source_ip: str | None = None
    summary: str
    is_failure: bool
    is_denied: bool
    is_routine_noise: bool


class AuditEventDetail(AuditEventOut):
    raw_payload_json: str


class AuditEventCreate(BaseModel):
    timestamp: datetime | None = None
    result: str | None = None
    actor: str | None = None
    action: str | None = None
    cluster_id: str | None = None
    source_ip: str | None = None
    summary: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
