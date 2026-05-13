"""Normalize stored actor values that carry a spurious "User:" prefix.

Events collected before the normalize_event() fix stored "User:u-xxxxx" and
"User:sa-xxxxx" verbatim in the actor column, splitting what is really one
principal into two distinct actors.  This migration strips the prefix in-place.

Only "User:u-" and "User:sa-" forms are touched.  "User:NNNN" (numeric) is
intentionally excluded — those rows need principalResourceId resolution, not
simple prefix stripping.

Revision ID: 0018_normalize_user_prefix_actors
Revises: 0017_add_client_tool
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

revision = "0018_normalize_user_prefix_actors"
down_revision = "0017_add_client_tool"
branch_labels = None
depends_on = None

_BATCH = 10_000


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "audit_events" not in inspector.get_table_names():
        return

    is_pg = bind.dialect.name == "postgresql"

    total = 0
    while True:
        if is_pg:
            # SUBSTRING(col FROM n) — 1-indexed, strips first 5 chars ("User:")
            result = bind.execute(text(
                "UPDATE audit_events"
                " SET actor = SUBSTRING(actor FROM 6),"
                "     actor_id = SUBSTRING(actor FROM 6)"
                " WHERE id IN ("
                "   SELECT id FROM audit_events"
                "   WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'"
                f"  LIMIT {_BATCH}"
                " )"
            ))
        else:
            # SQLite: SUBSTR(col, n) — also 1-indexed
            result = bind.execute(text(
                "UPDATE audit_events"
                " SET actor = SUBSTR(actor, 6),"
                "     actor_id = SUBSTR(actor, 6)"
                " WHERE rowid IN ("
                "   SELECT rowid FROM audit_events"
                "   WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'"
                f"  LIMIT {_BATCH}"
                " )"
            ))
        rows = result.rowcount
        total += rows
        if rows < _BATCH:
            break

    if total:
        op.get_bind().execute(text(
            "UPDATE audit_events"
            " SET actor_display_name = actor"
            " WHERE (actor LIKE 'u-%' OR actor LIKE 'sa-%')"
            "   AND (actor_display_name IS NULL OR actor_display_name = '')"
        ))


def downgrade() -> None:
    # Reversing is not safe without the original raw values; downgrade is a no-op.
    pass
