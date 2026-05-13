"""Add client_tool column to audit_events for narrative context.

client_tool maps the raw clientId (e.g. "rdkafka/1.9.2") to a human-readable
tool name (e.g. "librdkafka client (C/C++/Python/Go)") so the story engine can
say "Kalpak's VS Code ran a preflight check" instead of "Kalpak used proxy:1.0".

Revision ID: 0017_add_client_tool
Revises: 0016_add_attention_time_index
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "0017_add_client_tool"
down_revision = "0016_add_attention_time_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("audit_events")}
    if "client_tool" in existing:
        return  # already added by 0002_ensure_decision_columns or a prior run
    if bind.dialect.name == "postgresql":
        bind.execute(text("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS client_tool VARCHAR(128)"))
    else:
        op.add_column(
            "audit_events",
            sa.Column("client_tool", sa.String(128), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("audit_events", "client_tool")
