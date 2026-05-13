"""Add composite partial index on audit_events for non-noise attention queries.

Without this index the default GET /events query (is_routine_noise=false,
ordered by timestamp DESC) does a full sequential scan — observed 45 s wall
clock on a 1M-row table.

The partial index covers only the non-noise subset (~11 % of rows with
DROP_LOW_EVENTS enabled) so it is small and cheap to maintain.

Revision ID: 0016_add_attention_time_index
Revises: 0015_autovacuum_tuning
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0016_add_attention_time_index"
down_revision = "0015_autovacuum_tuning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # CREATE INDEX CONCURRENTLY must run outside a transaction block.
    # autocommit_block() (Alembic 1.7+) handles the COMMIT/BEGIN wrapping.
    with op.get_context().autocommit_block():
        op.execute(
            text("""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS
                    idx_audit_events_attention_time
                ON audit_events (timestamp DESC, signal_type)
                WHERE is_routine_noise = false
            """)
        )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_audit_events_attention_time"))
