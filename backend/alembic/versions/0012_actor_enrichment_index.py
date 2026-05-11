"""Add partial index on (actor, id DESC) for fast enrichment lookups.

Without this index, finding the most-recent qualifying actor_display_name
in a 7M+ row audit_events table takes ~49s. The partial index reduces that
to a sub-millisecond index scan per actor.

Revision ID: 0012_actor_enrichment_index
Revises: 0011_settings_table
Create Date: 2026-05-11
"""
from __future__ import annotations
from alembic import op

revision = "0012_actor_enrichment_index"
down_revision = "0011_settings_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_actor_display_enrichment "
        "ON audit_events (actor, id DESC) "
        "WHERE actor_display_name IS NOT NULL AND actor_display_name != ''"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "DROP INDEX IF EXISTS idx_audit_events_actor_display_enrichment"
    )
