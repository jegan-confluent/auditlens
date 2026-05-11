"""Add audit_event_patterns table for repetition detection.

Recurring (actor, action, resource) triples that fire > 10 times within a
10-minute window are recorded here so operators can suppress them or mark them
as expected automation without touching config files.

Revision ID: 0009_audit_event_patterns
Revises: 0007_noise_table
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0009_audit_event_patterns"
down_revision = "0007_noise_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa_inspect(bind).get_table_names()

    # The 0001_baseline migration runs Base.metadata.create_all() which creates
    # audit_event_patterns if AuditEventPattern is already in the ORM models.
    # In that case we only need to ensure the indexes exist.
    if "audit_event_patterns" not in existing_tables:
        op.create_table(
            "audit_event_patterns",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("pattern_key", sa.String(512), nullable=False),
            sa.Column("actor", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("resource_name", sa.Text(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("window_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'active'")),
            sa.Column("suppressed_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("suppressed_by", sa.Text(), nullable=True),
            sa.Column("suppression_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("pattern_key", name="uq_audit_event_patterns_pattern_key"),
        )

    existing_indexes = {idx["name"] for idx in sa_inspect(bind).get_indexes("audit_event_patterns")}
    if "idx_patterns_key" not in existing_indexes:
        op.create_index("idx_patterns_key", "audit_event_patterns", ["pattern_key"])
    if "idx_patterns_status" not in existing_indexes:
        op.create_index("idx_patterns_status", "audit_event_patterns", ["status"])
    if "idx_patterns_actor" not in existing_indexes:
        op.create_index("idx_patterns_actor", "audit_event_patterns", ["actor"])


def downgrade() -> None:
    op.drop_index("idx_patterns_actor", table_name="audit_event_patterns")
    op.drop_index("idx_patterns_status", table_name="audit_event_patterns")
    op.drop_index("idx_patterns_key", table_name="audit_event_patterns")
    op.drop_table("audit_event_patterns")
