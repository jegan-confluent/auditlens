"""Read-only resource catalog endpoint.

Returns resources aggregated from the resource_catalog table, which is
populated on every event ingestion by resource_service.upsert_resource_catalog.
Event counts are derived via a correlated subquery against audit_events.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.api.routes.patterns import _require_viewer
from backend.app.db.database import get_db
from backend.app.db.models import AuditEvent, ResourceCatalog

router = APIRouter(tags=["resources"])

_RESOURCE_CATALOG_TIMEOUT_MS = 10_000


class ResourceCatalogItem(BaseModel):
    resource_id: str
    resource_type: str
    resource_name: str
    display_name: str | None
    environment_id: str | None
    environment_name: str | None
    cluster_id: str | None
    first_seen: datetime
    last_seen: datetime
    event_count: int


class CatalogResponse(BaseModel):
    items: list[ResourceCatalogItem]
    total: int


def _build_catalog_stmt(
    resource_type: str | None,
    q: str | None,
    limit: int,
) -> Any:
    event_count_subq = (
        select(func.count(AuditEvent.id))
        .where(AuditEvent.resource_name == ResourceCatalog.resource_name)
        .correlate(ResourceCatalog)
        .scalar_subquery()
    )
    stmt = select(
        ResourceCatalog.resource_id,
        ResourceCatalog.resource_type,
        ResourceCatalog.resource_name,
        ResourceCatalog.display_name,
        ResourceCatalog.environment_id,
        ResourceCatalog.environment_name,
        ResourceCatalog.cluster_id,
        ResourceCatalog.first_seen_at.label("first_seen"),
        ResourceCatalog.last_seen_at.label("last_seen"),
        event_count_subq.label("event_count"),
    ).order_by(ResourceCatalog.last_seen_at.desc()).limit(limit)

    if resource_type:
        stmt = stmt.where(func.lower(ResourceCatalog.resource_type) == resource_type.lower())

    if q and q.strip():
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(ResourceCatalog.resource_id).like(pattern)
            | func.lower(ResourceCatalog.resource_name).like(pattern)
            | func.lower(ResourceCatalog.display_name).like(pattern)
        )
    return stmt


def _rows_to_items(rows: list[Any]) -> list[ResourceCatalogItem]:
    return [
        ResourceCatalogItem(
            resource_id=row.resource_id,
            resource_type=row.resource_type,
            resource_name=row.resource_name,
            display_name=row.display_name,
            environment_id=row.environment_id,
            environment_name=row.environment_name,
            cluster_id=row.cluster_id,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            event_count=row.event_count or 0,
        )
        for row in rows
    ]


@router.get("/resources/catalog", response_model=CatalogResponse)
def get_resource_catalog(
    resource_type: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> CatalogResponse:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {_RESOURCE_CATALOG_TIMEOUT_MS}"))
    rows = db.execute(_build_catalog_stmt(resource_type, q, limit)).all()
    items = _rows_to_items(rows)
    return CatalogResponse(items=items, total=len(items))


@router.get("/resources", response_model=list[ResourceCatalogItem])
def list_resources(
    resource_type: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _auth: None = Depends(_require_viewer),
) -> list[ResourceCatalogItem]:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = {_RESOURCE_CATALOG_TIMEOUT_MS}"))
    rows = db.execute(_build_catalog_stmt(resource_type, search, limit)).all()
    return _rows_to_items(rows)
