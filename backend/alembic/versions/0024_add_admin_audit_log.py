"""Add admin_audit_log for self-audit of admin/responder actions.

SOC2 / customer-compliance gap: AuditLens audits Confluent Cloud activity
but did not record its own privileged actions. If a responder suppresses
a pattern, an admin runs retention.cleanup, or an exporter downloads a
PII bundle, the record of "which token did what when" was missing.

The table is small (low write rate, mostly admin operations), so the
indexes are targeted at the GET /admin/audit-log query surface: filter
by actor and action, sort newest-first.

Revision ID: 0024_add_admin_audit_log
Revises: 0023_add_flattened_audit_fields
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "0024_add_admin_audit_log"
down_revision = "0023_add_flattened_audit_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if "admin_audit_log" in inspector.get_table_names():
        return

    # JSONB on Postgres for indexed/searchable detail blobs; JSON on
    # SQLite (used by unit-test fixtures + the demo profile).
    if bind.dialect.name == "postgresql":
        detail_col = sa.Column("detail", JSONB, nullable=True)
    else:
        detail_col = sa.Column("detail", sa.JSON, nullable=True)

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()") if bind.dialect.name == "postgresql" else sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text, nullable=True),
        sa.Column("target_id", sa.Text, nullable=True),
        detail_col,
        sa.Column("request_id", sa.Text, nullable=True),
    )

    # Index on timestamp DESC drives the default newest-first list query.
    # actor + action indexes cover the filter params on GET /admin/audit-log.
    op.create_index(
        "idx_admin_audit_log_timestamp",
        "admin_audit_log",
        ["timestamp"],
        postgresql_ops={"timestamp": "DESC"},
    )
    op.create_index("idx_admin_audit_log_actor", "admin_audit_log", ["actor"])
    op.create_index("idx_admin_audit_log_action", "admin_audit_log", ["action"])


def downgrade() -> None:
    op.drop_index("idx_admin_audit_log_action", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_log_actor", table_name="admin_audit_log")
    op.drop_index("idx_admin_audit_log_timestamp", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
