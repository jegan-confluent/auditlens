"""Add ipfilter_client_ip and ipfilter_resource_group to audit_events

Revision ID: 0028_add_ipfilter_fields
Revises: 0027_add_auth_role_fields
Create Date: 2026-06-09

Persist authorizationInfo.ipfilterAuthorization.{client_ip, resource_group}
so IP-filter-mediated denials can be distinguished from generic ACL/RBAC
denials and routed to a dedicated alert path. Both columns are NULL on the
vast majority of events; non-NULL marks an event subject to an IP filter
policy.

  ipfilter_client_ip       VARCHAR(45)   ← ipv4 or ipv6 max length
  ipfilter_resource_group  VARCHAR(255)  ← e.g. "MANAGEMENT"

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, existence check on SQLite.
No backfill — existing rows keep both columns NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "0028_add_ipfilter_fields"
down_revision: Union[str, Sequence[str], None] = "0027_add_auth_role_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("ipfilter_client_ip", "VARCHAR(45)"),
    ("ipfilter_resource_group", "VARCHAR(255)"),
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
