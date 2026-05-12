"""Fix actor_ip_baseline.is_trusted column type: INTEGER → BOOLEAN.

On systems where the table was first created by IpBaselineTracker's
create_all() before migration 0010 ran (or via an older code path that
used Integer instead of Boolean), the column ends up as INTEGER on
Postgres. The upsert then fails with:
  "column is_trusted is of type integer but expression is of type boolean"

This migration is a no-op if the column is already BOOLEAN or if the
table does not exist.

Revision ID: 0013_actor_ip_baseline_bool
Revises: 0012_actor_enrichment_index
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect as sa_inspect, text

revision = "0013_actor_ip_baseline_bool"
down_revision = "0012_actor_enrichment_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa_inspect(bind)
    if "actor_ip_baseline" not in inspector.get_table_names():
        return

    result = bind.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'actor_ip_baseline' AND column_name = 'is_trusted'"
        )
    )
    row = result.fetchone()
    if row is None or row[0].lower() == "boolean":
        return

    op.execute(
        "ALTER TABLE actor_ip_baseline "
        "ALTER COLUMN is_trusted TYPE boolean "
        "USING is_trusted::boolean"
    )
    op.execute("DROP INDEX IF EXISTS ix_actor_ip_baseline_is_trusted")
    op.execute(
        "CREATE INDEX ix_actor_ip_baseline_is_trusted "
        "ON actor_ip_baseline (is_trusted)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE actor_ip_baseline "
        "ALTER COLUMN is_trusted TYPE integer "
        "USING is_trusted::integer"
    )
