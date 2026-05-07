"""Smoke test: the Alembic baseline applies cleanly to a fresh in-memory SQLite DB."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _build_alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_baseline_migration_applies_to_fresh_sqlite(tmp_path):
    db_path = tmp_path / "alembic_smoke.db"
    database_url = f"sqlite:///{db_path}"
    cfg = _build_alembic_config(database_url)

    # upgrade head: must complete without raising on a fresh database.
    command.upgrade(cfg, "head")

    # Verify the canonical tables now exist.
    from sqlalchemy import create_engine, inspect

    engine = create_engine(database_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"audit_events", "audit_event_triage", "resource_catalog"}.issubset(tables)
    engine.dispose()


def test_baseline_migration_is_idempotent(tmp_path):
    """Running upgrade head twice must be a no-op the second time."""
    db_path = tmp_path / "alembic_idempotent.db"
    database_url = f"sqlite:///{db_path}"
    cfg = _build_alembic_config(database_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
