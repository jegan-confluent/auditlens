"""Autovacuum tuning for high-write audit tables.

Default autovacuum settings (scale_factor=0.2) trigger vacuuming at
20% dead-tuple ratio. For audit_events (millions of rows, hundreds of
INSERTs/s), that means autovacuum runs infrequently and dead tuples
accumulate — observed 1.4M dead tuples causing 61-second inserts.

Setting scale_factor=0 + threshold=10_000 makes autovacuum trigger
every 10_000 dead tuples regardless of table size. This keeps bloat low
at the cost of slightly more frequent (but cheaper) vacuums.

Applied manually today via psql after observing the performance
regression; this migration makes it permanent so fresh deployments
don't hit the same issue.

Revision ID: 0015_autovacuum_tuning
Revises: 0014_clean_json_blob_actor_display_names
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0015_autovacuum_tuning"
down_revision = "0014_clean_json_blob_actor_display_names"
branch_labels = None
depends_on = None

_TABLES = ("audit_events", "audit_events_noise")

_ALTER = (
    "autovacuum_vacuum_scale_factor = 0, "
    "autovacuum_vacuum_threshold = 10000"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in _TABLES:
        bind.execute(text(f"ALTER TABLE {table} SET ({_ALTER})"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in _TABLES:
        bind.execute(text(
            f"ALTER TABLE {table} RESET ("
            "autovacuum_vacuum_scale_factor, "
            "autovacuum_vacuum_threshold)"
        ))
