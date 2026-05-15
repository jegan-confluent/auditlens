"""fix: actor_enriched_at String to DateTime

Revision ID: 0022_actor_enriched_at_datetime
Revises: 0021_add_feedback_table
Create Date: 2026-05-15

Change actor_enriched_at from VARCHAR(64) storing ISO strings to a proper
TIMESTAMP WITH TIME ZONE column. Existing ISO-string values are cast
automatically by PostgreSQL's USING clause; SQLite batch-alter is a no-op
type change since SQLite ignores column types.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0022_actor_enriched_at_datetime'
down_revision: Union[str, Sequence[str], None] = '0021_add_feedback_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE audit_events "
            "ALTER COLUMN actor_enriched_at TYPE TIMESTAMP WITH TIME ZONE "
            "USING actor_enriched_at::TIMESTAMPTZ"
        )
    else:
        with op.batch_alter_table("audit_events") as batch_op:
            batch_op.alter_column(
                "actor_enriched_at",
                existing_type=sa.String(64),
                type_=sa.DateTime(timezone=True),
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE audit_events "
            "ALTER COLUMN actor_enriched_at TYPE VARCHAR(64) "
            "USING actor_enriched_at::TEXT"
        )
    else:
        with op.batch_alter_table("audit_events") as batch_op:
            batch_op.alter_column(
                "actor_enriched_at",
                existing_type=sa.DateTime(timezone=True),
                type_=sa.String(64),
                existing_nullable=True,
            )
