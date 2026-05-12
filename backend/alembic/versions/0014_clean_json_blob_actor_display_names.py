"""Clean JSON blob values stored as actor_display_name.

Some enrichment paths serialised nested API response objects as JSON strings
into the actor_display_name column (e.g. '{"externalAccount":{"subject":"Confluent"}}').
This migration NULLs those rows so the enrichment property falls through to
live enrichment or the raw actor ID.

Revision ID: 0014_clean_json_blob_actor_display_names
Revises: 0013_actor_ip_baseline_bool
Create Date: 2026-05-12
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0014_clean_json_blob_actor_display_names"
down_revision = "0013_actor_ip_baseline_bool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            "UPDATE audit_events SET actor_display_name = NULL "
            "WHERE actor_display_name LIKE '{%' OR actor_display_name LIKE '[%'"
        )
    )


def downgrade() -> None:
    pass
