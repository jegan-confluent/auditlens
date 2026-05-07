"""Add ON DELETE CASCADE between audit_event_triage and audit_events.

Retention cleanup deletes from ``audit_events`` by timestamp. Without a
cascading FK the matching rows in ``audit_event_triage`` were left orphaned
because the link was a string-equal-string fingerprint, not a database
constraint.

This revision adds the FK so:

* Postgres: a real FK with ``ON DELETE CASCADE`` is created between
  ``audit_event_triage.event_fingerprint`` and ``audit_events.event_fingerprint``.
* SQLite: the column already exists; SQLAlchemy emits a ``foreign_keys`` PRAGMA
  on connect via ``backend.app.db.database``. Because SQLite cannot ``ALTER
  TABLE`` to add a constraint without rebuilding, the application also clears
  the orphan rows explicitly inside ``cleanup_retention`` (belt-and-braces
  fallback).

Revision ID: 0003_triage_cascade_fk
Revises: 0002_ensure_decision_columns
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "0003_triage_cascade_fk"
down_revision = "0002_ensure_decision_columns"
branch_labels = None
depends_on = None


_FK_NAME = "fk_audit_event_triage_event_fingerprint"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite cannot add a FK to an existing table via ALTER TABLE. The
        # baseline already declares the FK on a fresh DB; the application-level
        # fallback in cleanup_retention takes care of legacy SQLite installs.
        return
    inspector = inspect(bind)
    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("audit_event_triage")}
    if _FK_NAME in existing_fks:
        return
    op.create_foreign_key(
        _FK_NAME,
        "audit_event_triage",
        "audit_events",
        ["event_fingerprint"],
        ["event_fingerprint"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = inspect(bind)
    existing_fks = {fk["name"] for fk in inspector.get_foreign_keys("audit_event_triage")}
    if _FK_NAME not in existing_fks:
        return
    op.drop_constraint(_FK_NAME, "audit_event_triage", type_="foreignkey")
