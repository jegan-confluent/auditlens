"""Add app_settings table for encrypted key-value config storage.

Revision ID: 0011_settings_table
Revises: 0010_actor_ip_baseline
Create Date: 2026-05-11
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0011_settings_table"
down_revision = "0010_actor_ip_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()
    if "app_settings" in existing_tables:
        return
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_enc", sa.LargeBinary(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category", "key", name="uq_app_settings_category_key"),
    )
    op.create_index("idx_app_settings_category", "app_settings", ["category"])


def downgrade() -> None:
    op.drop_index("idx_app_settings_category", table_name="app_settings")
    op.drop_table("app_settings")
