"""Create audit_events_noise table for the bulk-noise lane.

Routine auth checks and produce/fetch traffic dominate audit volume
(~83%) but never need full enrichment. Splitting them into a dedicated
INSERT-only table with no event_fingerprint, no UNIQUE constraint, and
two indexes only drops the per-event INSERT cost dramatically:

  audit_events:        50 columns, ~14 indexes, UPSERT path (~5 ms/row)
  audit_events_noise:  11 columns,  2 indexes, INSERT path  (~0.1 ms/row)

The table is rebuildable from Kafka topics, so retention follows
EVENT_RETENTION_DAYS (default 7 days).

Revision ID: 0007_noise_table
Revises: 0006_drop_unused_indexes
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect


revision = "0007_noise_table"
down_revision = "0006_drop_unused_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # The baseline (0001) creates all model tables via create_all(checkfirst=True),
    # so audit_events_noise may already exist on fresh deployments.
    if sa_inspect(bind).has_table("audit_events_noise"):
        return

    if dialect == "postgresql":
        id_col = sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True)
    else:
        # SQLite needs plain INTEGER PRIMARY KEY to alias ROWID and get
        # autoincrement; BigInteger doesn't qualify.
        id_col = sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)

    op.create_table(
        "audit_events_noise",
        id_col,
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("resource_name", sa.String(length=512), nullable=True),
        sa.Column("source_ip", sa.String(length=128), nullable=True),
        sa.Column("environment_id", sa.String(length=255), nullable=True),
        sa.Column("cluster_id", sa.String(length=255), nullable=True),
        sa.Column("is_denied", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Two indexes only — anything else would re-introduce the per-INSERT
    # cost we are trying to avoid.
    op.create_index(
        "idx_noise_timestamp",
        "audit_events_noise",
        [sa.text("timestamp DESC")],
    )
    op.create_index(
        "idx_noise_actor",
        "audit_events_noise",
        ["actor"],
    )


def downgrade() -> None:
    op.drop_index("idx_noise_actor", table_name="audit_events_noise")
    op.drop_index("idx_noise_timestamp", table_name="audit_events_noise")
    op.drop_table("audit_events_noise")
