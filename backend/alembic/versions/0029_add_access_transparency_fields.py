"""Add at_justification and at_operator to audit_events

Revision ID: 0029_add_access_transparency_fields
Revises: 0028_add_ipfilter_fields
Create Date: 2026-06-09

Persist Access Transparency event fields so the new /access-transparency
view can render the operator + business justification per row without
parsing raw_payload_json.

Both columns are NULL on the vast majority of events; non-NULL marks an
io.confluent.cloud/access-transparency event recorded when Confluent
personnel access customer resources.

  at_justification  TEXT          ← data.justification (free-form reason)
  at_operator       VARCHAR(255)  ← data.operator (Confluent personnel id)

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, existence check on SQLite.
No backfill — existing rows keep both columns NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "0029_add_access_transparency_fields"
down_revision: Union[str, Sequence[str], None] = "0028_add_ipfilter_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("at_justification", "TEXT"),
    ("at_operator", "VARCHAR(255)"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events")}
    dialect = bind.dialect.name
    for name, type_sql in _NEW_COLUMNS:
        if name in existing:
            continue
        if dialect == "postgresql":
            bind.execute(text(f"ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS {name} {type_sql}"))
        else:
            bind.execute(text(f"ALTER TABLE audit_events ADD COLUMN {name} {type_sql}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events")}
    with op.batch_alter_table("audit_events") as batch_op:
        for name, _ in reversed(_NEW_COLUMNS):
            if name in existing:
                batch_op.drop_column(name)
