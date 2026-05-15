from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from src.product.event_normalization import canonical_resource_type
from backend.app.services.event_service import derive_plane_type


class AuditEventListOut(BaseModel):
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
    resource_display_name: str
    cluster_id: str | None = None
    cluster_name: str | None = None
    source_ip: str | None = None
    summary: str
    is_failure: bool
    is_denied: bool
    is_routine_noise: bool
    impact_type: str
    risk_level: str
    change_type: str
    resource_family: str
    event_title: str
    event_summary: str
    subject: str
    subject_type: str
    actor_id: str | None = None
    actor_display_name: str
    actor_email: str | None = None
    actor_type: str
    actor_raw_id: str | None = None
    actor_source: str = "fallback"
    actor_confidence: str = "low"
    actor_enriched_at: datetime | str | None = None

    @field_validator("actor_enriched_at", mode="before")
    @classmethod
    def _coerce_actor_enriched_at(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)
    resource_display_short: str
    source_context: str
    environment_id: str | None = None
    environment_name: str | None = None
    parent_resource: str | None = None
    resource_scope: str
    resource_criticality: str
    blast_radius_hint: str
    production_hint: str
    flink_region: str | None = None
    network_id: str | None = None
    signal_type: str
    signal_reason: str
    decision_reason: str
    decision_label: str
    recommended_action: str
    client_tool: str | None = None
    triage_status: str = "open"
    triage_actor: str | None = None
    triage_timestamp: str | None = None
    triage_note: str | None = None
    suppressed: bool = False

    @field_validator("resource_type", mode="before")
    @classmethod
    def normalize_resource_type(cls, value: object) -> str:
        return canonical_resource_type(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def plane_type(self) -> str:
        return derive_plane_type(self.action, getattr(self, "resource_family", None), getattr(self, "action_category", None))


class AuditEventDetailOut(AuditEventListOut):
    source_display: str
    source_reason: str
    client_id: str | None = None
    connection_id: str | None = None
    request_id: str | None = None
    raw_payload_json: str | None = None
    rbac_role: str | None = None
    rbac_scope: str | None = None


AuditEventOut = AuditEventListOut
AuditEventDetail = AuditEventDetailOut


class AuditEventCreate(BaseModel):
    timestamp: datetime | None = None
    result: str | None = None
    actor: str | None = None
    action: str | None = None
    cluster_id: str | None = None
    source_ip: str | None = None
    summary: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class AuditNoiseListOut(BaseModel):
    """Item schema for /events?show_noise=true.

    Mirrors the physical columns of the audit_events_noise table
    (migration 0007). Decision fields like signal_type are constants for
    every noise row (`signal_type='noise'`, `signal_reason='bulk_noise'`)
    and are emitted unconditionally so clients can render a uniform list.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    actor: str | None = None
    action: str | None = None
    result: str | None = None
    resource_name: str | None = None
    source_ip: str | None = None
    environment_id: str | None = None
    cluster_id: str | None = None
    is_denied: bool = False
    # Constants — see class docstring.
    signal_type: str = "noise"
    signal_reason: str = "bulk_noise"
    source: str = "noise_table"
