"""Add auth_role and auth_role_target columns to audit_events

Revision ID: 0027_add_auth_role_fields
Revises: 0026_audit_events_noise_optional_dedup
Create Date: 2026-06-09

Adds two columns to support the privilege-escalation alert path:

  auth_role          VARCHAR(255)  ← request.data.role_name (BindRoleForPrincipal)
                                     or authorizationInfo.rbacAuthorization.role
  auth_role_target   VARCHAR(255)  ← request.data.principal (target of the grant)

These were previously dropped before DB write — flatten_audit extracted
rbacAuthorization.role into rbacRole but it never survived to a column.
With dedicated columns, the signal classifier can fire a
privilege_escalation alert when an admin-level role binding is observed,
and the event browser can filter by auth_role.

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, existence check on SQLite.
No backfill — existing rows keep both columns NULL. New events populate
them going forward.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "0027_add_auth_role_fields"
down_revision: Union[str, Sequence[str], None] = "0026_audit_events_noise_optional_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("auth_role", "VARCHAR(255)"),
    ("auth_role_target", "VARCHAR(255)"),
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
