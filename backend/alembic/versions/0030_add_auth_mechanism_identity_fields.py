"""Add auth_mechanism, identity, original_principal, assigned_principals

Revision ID: 0030_add_auth_mechanism_identity_fields
Revises: 0029_add_access_transparency_fields
Create Date: 2026-06-09

flatten_audit() already extracts these from authenticationInfo into the
in-memory dict, but every value was dropped before DB write — so the
columns never existed on audit_events and the filters / UI drawer had no
data to render.

  auth_mechanism      VARCHAR(50)   ← authenticationInfo.metadata.mechanism
  identity            VARCHAR(512)  ← authenticationInfo.identity
  original_principal  VARCHAR(512)  ← authenticationInfo.originalPrincipal
  assigned_principals TEXT          ← authorizationInfo.assignedPrincipals
                                      (JSON-encoded for dialect parity)

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, existence check on SQLite.
No backfill — existing rows keep all four columns NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "0030_add_auth_mechanism_identity_fields"
down_revision: Union[str, Sequence[str], None] = "0029_add_access_transparency_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("auth_mechanism", "VARCHAR(50)"),
    ("identity", "VARCHAR(512)"),
    ("original_principal", "VARCHAR(512)"),
    ("assigned_principals", "TEXT"),
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
