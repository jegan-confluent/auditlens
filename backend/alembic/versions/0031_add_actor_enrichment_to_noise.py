"""Add actor_display_name + actor_email to audit_events_noise

Revision ID: 0031_add_actor_enrichment_to_noise
Revises: 0030_add_auth_mechanism_identity_fields
Create Date: 2026-06-10

The forwarder's short-circuit lane pushes kafka.Authentication and other
BULK_NOISE_METHODS events to audit_events_noise via minimal_normalize.
Until now the noise table held only the raw `actor` string — every
display surface (Auth Analytics, /events?show_noise=true) had to fall
back to "User:XXXXXXX" because the human-readable fields were never
captured at ingest.

  actor_display_name  VARCHAR(255)  ← from enrich_actor(...).actor_display_name
  actor_email         VARCHAR(255)  ← from enrich_actor(...).actor_email

Idempotent: ADD COLUMN IF NOT EXISTS on Postgres, existence check on SQLite.
No backfill — existing rows keep both columns NULL; new ingest populates
them when enrich_actor returns a non-fallback identity.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text


revision: str = "0031_add_actor_enrichment_to_noise"
down_revision: Union[str, Sequence[str], None] = "0030_add_auth_mechanism_identity_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    ("actor_display_name", "VARCHAR(255)"),
    ("actor_email", "VARCHAR(255)"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events_noise" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events_noise")}
    dialect = bind.dialect.name
    for name, type_sql in _NEW_COLUMNS:
        if name in existing:
            continue
        if dialect == "postgresql":
            bind.execute(text(f"ALTER TABLE audit_events_noise ADD COLUMN IF NOT EXISTS {name} {type_sql}"))
        else:
            bind.execute(text(f"ALTER TABLE audit_events_noise ADD COLUMN {name} {type_sql}"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events_noise" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("audit_events_noise")}
    with op.batch_alter_table("audit_events_noise") as batch_op:
        for name, _ in reversed(_NEW_COLUMNS):
            if name in existing:
                batch_op.drop_column(name)
