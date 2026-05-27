from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from backend.app.schemas.event import AuditEventListOut, AuditNoiseListOut


class HealthResponse(BaseModel):
    status: str
    service: str
    database_mode: str


class EventListResponse(BaseModel):
    items: list[AuditEventListOut]
    limit: int
    offset: int
    total: int
    scanned_events: int = 0
    signal_filter_applied: bool = False
    hide_noise_applied: bool = False
    result_limit_reached: bool = False
    next_cursor: str | None = None
    debug: dict[str, Any] | None = None


class FilterOptionsResponse(BaseModel):
    resource_types: list[str]
    action_categories: list[str]
    results: list[str]
    actors: list[str]
    environments: list[str] = []


class NoiseSummaryEntry(BaseModel):
    action: str
    count: int


class NoiseSummary(BaseModel):
    total_noise_events: int
    top_noise_methods: list[NoiseSummaryEntry]
    noise_table_rows: int
    noise_retention_days: int


class SummaryResponse(BaseModel):
    total_events: int
    scanned_events: int = 0
    failures: int
    denials: int
    noise_count: int = 0
    informational_count: int = 0
    attention_count: int = 0
    action_required_count: int = 0
    failure_count: int = 0
    denied_count: int = 0
    destructive_count: int = 0
    configuration_change_count: int = 0
    access_change_count: int = 0
    top_subjects: list[dict[str, Any]] = []
    top_resources: list[dict[str, Any]] = []
    top_actions: list[dict[str, Any]] = []
    top_signal_reasons: list[dict[str, Any]] = []
    flow_groups: list[dict[str, Any]] = []
    summary_scope: str = "complete"
    sample_limit: int = 0
    sample_warning: str | None = None
    overall_status: str = "all_clear"
    headline: str = "No action needed. Most activity is routine authentication and authorization."
    short_digest: str = "No destructive or failed events detected in the selected window."
    by_action_category: dict[str, int]
    by_resource_type: dict[str, int]
    by_result: dict[str, int]
    by_environment: dict[str, int] = {}
    by_cluster: dict[str, int] = {}
    by_hour: list[int] = []
    # Populated only when ?include_noise=true is set on the request. None
    # when the noise table is unavailable / query failed.
    noise_summary: NoiseSummary | None = None


class MethodDistributionEntry(BaseModel):
    """Per-method aggregate row for /summary/methods.

    ``table`` is `"signal"` for rows derived from audit_events and
    `"noise"` for rows derived from audit_events_noise. When the same
    action appears in both tables the entry shows the combined count and
    the higher-priority signal_type ("noise" only if the action is
    exclusively noise).
    """
    action: str
    count: int
    signal_type: str
    table: Literal["signal", "noise"]
    last_seen: datetime | None = None


class MethodDistributionResponse(BaseModel):
    methods: list[MethodDistributionEntry]
    total_signal_events: int
    total_noise_events: int
    generated_at: datetime


class EventListNoiseResponse(BaseModel):
    """Response shape for /events?show_noise=true. The noise table has 9
    physical columns — much fewer than audit_events — so we use a
    dedicated item schema instead of overloading AuditEventListOut and
    inventing default values for fields that don't exist on noise rows."""
    items: list[AuditNoiseListOut]
    limit: int
    offset: int
    total: int
    source: Literal["noise_table"] = "noise_table"


class PipelineLag(BaseModel):
    """End-to-end ingestion lag, combining the consumer-side view from the
    forwarder /health endpoint with the DB-side `MAX(timestamp)` from
    Postgres. `status` is the operator-facing single signal that drives
    the System-page banner.
    """
    kafka_consumer_lag_messages: int | None = None
    db_latest_event_at: str | None = None
    forwarder_last_write_at: str | None = None
    db_behind_seconds: int | None = None
    replay_recommended: bool = False
    status: Literal["healthy", "degraded", "stalled", "unknown"] = "unknown"


class SystemStatusResponse(BaseModel):
    consumer_state: str
    last_successful_poll: str | None
    retry_count: int
    consecutive_error_count: int
    last_error: str | None
    consumer_lag: int | None
    records_consumed_total: int
    db_writer_enabled: bool = False
    db_writer_state: str = "unknown"
    db_write_success_total: int = 0
    db_write_error_total: int = 0
    db_write_batch_size: int = 0
    db_last_successful_write: str | None = None
    db_last_error: str | None = None
    db_last_cleanup_at: str | None = None
    db_last_cleanup_deleted_count: int = 0
    storage_usage: dict[str, Any]
    database_mode: str
    db_health: dict[str, Any] | None = None
    pipeline_lag: PipelineLag | None = None
    pipeline_status: Literal["healthy", "degraded", "stalled", "unknown"] = "unknown"
    storage_health: dict[str, Any] | None = None
    auth_enabled: bool = False
    confluent_configured: bool = False
    effective_retention: dict[str, int] | None = None
    schema_registry: dict[str, Any] | None = None
