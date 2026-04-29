from typing import Any

from pydantic import BaseModel

from backend.app.schemas.event import AuditEventOut


class HealthResponse(BaseModel):
    status: str
    service: str
    database_mode: str


class EventListResponse(BaseModel):
    items: list[AuditEventOut]
    limit: int
    offset: int
    total: int


class FilterOptionsResponse(BaseModel):
    resource_types: list[str]
    action_categories: list[str]
    results: list[str]
    actors: list[str]


class SummaryResponse(BaseModel):
    total_events: int
    failures: int
    denials: int
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
