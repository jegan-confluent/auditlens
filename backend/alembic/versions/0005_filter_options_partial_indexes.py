"""Partial indexes that back /filters/options dropdown population.

The four dropdown queries (``resource_type``, ``actor``, ``action_category``,
``result``) all filter by ``col IS NOT NULL AND col != ''``. The columns are
NOT NULL by schema, so the partial predicate primarily excludes empty strings
— a small reduction in size but it exactly matches the WHERE clause the
service issues, which lets the planner pick this index over the plain ones
for index-only scans where applicable.

``resource_type`` and ``actor`` are the costliest of the four (most distinct
values + highest cardinality of values to GROUP BY). ``action_category`` and
``result`` already have small enough domains that the existing
``idx_audit_events_action_category`` / ``idx_audit_events_result`` plain
indexes are sufficient.

Revision ID: 0005_filter_options_partial_indexes
Revises: 0004_summary_aggregation_indexes
Create Date: 2026-05-08
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0005_filter_options_partial_indexes"
down_revision = "0004_summary_aggregation_indexes"
branch_labels = None
depends_on = None


_INDEX_NAMES: tuple[str, ...] = (
    "idx_audit_events_resource_type_notnull",
    "idx_audit_events_actor_notnull",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        statements = (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_events_resource_type_notnull "
            "ON audit_events (resource_type) WHERE resource_type IS NOT NULL AND resource_type != ''",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_events_actor_notnull "
            "ON audit_events (actor) WHERE actor IS NOT NULL AND actor != ''",
        )
        with op.get_context().autocommit_block():
            for sql in statements:
                op.execute(text(sql))
        return

    sqlite_statements = (
        "CREATE INDEX IF NOT EXISTS idx_audit_events_resource_type_notnull "
        "ON audit_events (resource_type) WHERE resource_type IS NOT NULL AND resource_type != ''",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_actor_notnull "
        "ON audit_events (actor) WHERE actor IS NOT NULL AND actor != ''",
    )
    for sql in sqlite_statements:
        op.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            for name in _INDEX_NAMES:
                op.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
        return
    for name in _INDEX_NAMES:
        op.execute(text(f"DROP INDEX IF EXISTS {name}"))
