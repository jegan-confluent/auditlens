"""Add 6 flattened audit fields to audit_events

Revision ID: 0023_add_flattened_audit_fields
Revises: 0022_actor_enriched_at_datetime
Create Date: 2026-05-19

Flatten the most useful data_json subfields into top-level audit_events
columns so Tableflow surfaces them as queryable columns rather than
hiding everything inside an opaque JSON string.

  auth_granted          BOOLEAN       ← authorizationInfo.granted
  auth_operation        VARCHAR(255)  ← authorizationInfo.operation
  auth_resource_type    VARCHAR(128)  ← authorizationInfo.resourceType
  auth_pattern_type     VARCHAR(64)   ← authorizationInfo.patternType
  result_resource_id    VARCHAR(255)  ← result.data.id
  access_type           VARCHAR(64)   ← request.accessType

Idempotent: uses ``ADD COLUMN IF NOT EXISTS`` on Postgres and a column-
existence check on SQLite, matching the pattern in 0002. Required because
0002_ensure_decision_columns iterates ``AUDIT_EVENT_COLUMNS`` from
``backend/app/db/column_spec.py`` and may have already added these
columns during its own run on databases that import column_spec at
baseline-create time.

No backfill — existing rows keep these columns NULL. New events written
by event_normalization.normalize_event() populate them going forward.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "0023_add_flattened_audit_fields"
down_revision: Union[str, Sequence[str], None] = "0022_actor_enriched_at_datetime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("auth_granted", "BOOLEAN"),
    ("auth_operation", "VARCHAR(255)"),
    ("auth_resource_type", "VARCHAR(128)"),
    ("auth_pattern_type", "VARCHAR(64)"),
    ("result_resource_id", "VARCHAR(255)"),
    ("access_type", "VARCHAR(64)"),
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
