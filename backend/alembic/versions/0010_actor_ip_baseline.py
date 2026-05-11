"""Add actor_ip_baseline table for per-actor IP tracking.

Records every (actor, source_ip) pair seen in audit events. Used to detect
new/anomalous IPs for a given actor and to persist cloud provider attribution.

Revision ID: 0010_actor_ip_baseline
Revises: 0009_audit_event_patterns
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0010_actor_ip_baseline"
down_revision = "0009_audit_event_patterns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()
    if "actor_ip_baseline" in existing_tables:
        return

    op.create_table(
        "actor_ip_baseline",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("source_ip", sa.String(128), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cloud_provider", sa.String(64), nullable=True),
        sa.Column("region", sa.String(128), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor", "source_ip", name="uq_actor_ip"),
    )
    op.create_index("ix_actor_ip_baseline_actor", "actor_ip_baseline", ["actor"])
    op.create_index("ix_actor_ip_baseline_is_trusted", "actor_ip_baseline", ["is_trusted"])


def downgrade() -> None:
    op.drop_index("ix_actor_ip_baseline_is_trusted", table_name="actor_ip_baseline")
    op.drop_index("ix_actor_ip_baseline_actor", table_name="actor_ip_baseline")
    op.drop_table("actor_ip_baseline")
