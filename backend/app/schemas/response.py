from typing import Any

from pydantic import BaseModel

from backend.app.schemas.event import AuditEventListOut


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
    debug: dict[str, Any] | None = None


class FilterOptionsResponse(BaseModel):
    resource_types: list[str]
    action_categories: list[str]
    results: list[str]
    actors: list[str]


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
