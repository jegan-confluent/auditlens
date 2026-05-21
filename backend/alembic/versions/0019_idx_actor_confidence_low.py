"""Add partial index on actor_confidence = 'low' to speed up actor backfill.

The backfill query scans for rows needing re-enrichment, one condition being
actor_confidence = 'low'. Without an index this forces a full sequential scan
on audit_events (4.9M+ rows), consistently triggering the statement timeout.

Uses plain ``CREATE INDEX IF NOT EXISTS`` — the prior
``autocommit_block`` + ``CONCURRENTLY`` form failed
``AssertionError: assert self._transaction is not None`` under env.py's
transactional migration runner. See 0004 for the full rationale.

Revision ID: 0019_idx_actor_confidence_low
Revises: 0018_strip_actor_user_prefix
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0019_idx_actor_confidence_low"
down_revision = "0018_strip_actor_user_prefix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_actor_confidence_low"
        " ON audit_events (id)"
        " WHERE actor_confidence = 'low'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(text(
        "DROP INDEX IF EXISTS idx_audit_events_actor_confidence_low"
    ))
