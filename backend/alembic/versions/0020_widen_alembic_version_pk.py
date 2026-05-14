"""Widen alembic_version.version_num from VARCHAR(32) to VARCHAR(64).

Alembic defaults to VARCHAR(32) for the version_num column. Revision IDs
longer than 32 characters (e.g. descriptive slugs) will overflow and raise
a DataError on Postgres. This migration widens the column so longer IDs are
stored safely.

No-op on SQLite — SQLite does not enforce VARCHAR lengths.

Revision ID: 0020_widen_alembic_version_pk
Revises: 0019_idx_actor_confidence_low
Create Date: 2026-05-14
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0020_widen_alembic_version_pk"
down_revision = "0019_idx_actor_confidence_low"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(text(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(text(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)"
    ))
