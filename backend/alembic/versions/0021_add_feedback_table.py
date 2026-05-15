"""Add feedback table for user-submitted bug reports, feature requests, and general feedback.

Revision ID: 0021_add_feedback_table
Revises: 0020_widen_alembic_version_pk
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0021_add_feedback_table"
down_revision = "0020_widen_alembic_version_pk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()
    if "feedback" in existing_tables:
        return

    # Create the enum type on Postgres; SQLite ignores it.
    if bind.dialect.name == "postgresql":
        op.execute("CREATE TYPE feedback_type AS ENUM ('bug', 'feature', 'general')")
        type_col = sa.Column("type", sa.Enum("bug", "feature", "general", name="feedback_type"), nullable=False)
    else:
        type_col = sa.Column("type", sa.String(32), nullable=False)

    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        type_col,
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("page_context", sa.String(200), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_feedback_created_at", "feedback", ["created_at"], postgresql_ops={"created_at": "DESC"})


def downgrade() -> None:
    op.drop_index("idx_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS feedback_type")
