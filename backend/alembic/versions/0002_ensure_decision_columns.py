"""Idempotent additive columns on ``audit_events``.

This revision codifies the ``ALTER TABLE`` patches that were previously hand
rolled inside:

* ``backend/app/db/database.py::_ensure_audit_event_columns``
* ``src/product/db_writer.py::DatabaseWriter._ensure_columns``

A Postgres production database that was created against an older release may
be missing these columns. The baseline ``create_all`` does not add columns to
existing tables, so this revision exists to additively patch them.

Each column is added with ``IF NOT EXISTS`` semantics on Postgres and a
column-existence check on SQLite, mirroring the previous behaviour.

Revision ID: 0002_ensure_decision_columns
Revises: 0001_baseline
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision = "0002_ensure_decision_columns"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


# Column name -> SQL type. Mirrors the dictionary in
# database.py::_ensure_audit_event_columns and db_writer.py::_ensure_columns.
_AUDIT_EVENTS_COLUMNS: dict[str, str] = {
    "actor_id": "VARCHAR(255)",
    "actor_display_name": "VARCHAR(255)",
    "actor_email": "VARCHAR(255)",
    "actor_type": "VARCHAR(64)",
    "actor_source": "VARCHAR(64)",
    "actor_confidence": "VARCHAR(32)",
    "actor_enriched_at": "VARCHAR(64)",
    "source_context": "VARCHAR(255)",
    "client_id": "VARCHAR(255)",
    "connection_id": "VARCHAR(255)",
    "request_id": "VARCHAR(255)",
    "environment_id": "VARCHAR(255)",
    "cluster_name": "VARCHAR(255)",
    "environment_name": "VARCHAR(255)",
    "parent_resource": "VARCHAR(255)",
    "resource_scope": "VARCHAR(512)",
    "resource_display_name": "VARCHAR(768)",
    "resource_criticality": "VARCHAR(32)",
    "blast_radius_hint": "VARCHAR(64)",
    "production_hint": "VARCHAR(64)",
    "flink_region": "VARCHAR(255)",
    "network_id": "VARCHAR(255)",
    "signal_type": "VARCHAR(32)",
    "signal_reason": "VARCHAR(128)",
    "impact_type": "VARCHAR(64)",
    "risk_level": "VARCHAR(32)",
    "change_type": "VARCHAR(32)",
    "resource_family": "VARCHAR(64)",
    "event_title": "VARCHAR(255)",
    "event_summary": "VARCHAR(768)",
    "decision_reason": "VARCHAR(255)",
    "decision_label": "VARCHAR(32)",
    "recommended_action": "VARCHAR(255)",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events")}
    dialect = bind.dialect.name
    for name, type_sql in _AUDIT_EVENTS_COLUMNS.items():
        if name in existing:
            continue
        if dialect == "postgresql":
            bind.execute(text(f"ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS {name} {type_sql}"))
        else:
            bind.execute(text(f"ALTER TABLE audit_events ADD COLUMN {name} {type_sql}"))


def downgrade() -> None:
    # Intentionally a no-op. These columns are additive and dropping them would
    # discard enrichment data persisted by older forwarder versions.
    return
