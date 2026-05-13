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

from backend.app.db.column_spec import AUDIT_EVENT_COLUMNS

# revision identifiers, used by Alembic.
revision = "0002_ensure_decision_columns"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events")}
    dialect = bind.dialect.name
    for name, type_sql in AUDIT_EVENT_COLUMNS.items():
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
