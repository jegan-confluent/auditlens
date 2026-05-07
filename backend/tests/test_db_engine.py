"""Tests for the SQLAlchemy engine builder.

These verify the pool tuning + statement_timeout policy without requiring a
real Postgres server.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.db import database


def test_postgres_engine_sets_statement_timeout():
    """When DATABASE_URL is Postgres the engine wires connect_args options."""
    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs

        class _FakeEngine:
            def dispose(self):
                pass

        return _FakeEngine()

    with patch.object(database, "create_engine", side_effect=fake_create_engine):
        database.build_engine("postgresql://auditlens:auditlens@127.0.0.1:5432/auditlens")

    assert captured["url"].startswith("postgresql+psycopg://")
    kwargs = captured["kwargs"]
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_timeout"] == 30
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_pre_ping"] is True
    connect_args = kwargs["connect_args"]
    assert connect_args == {"options": "-c statement_timeout=30000"}


def test_sqlite_engine_does_not_set_statement_timeout(tmp_path):
    """SQLite must keep its existing connect_args (check_same_thread) only."""
    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs

        class _FakeEngine:
            def dispose(self):
                pass

        return _FakeEngine()

    db_path = tmp_path / "engine.db"
    with patch.object(database, "create_engine", side_effect=fake_create_engine):
        with patch.object(database, "event"):  # avoid registering the FK PRAGMA listener on a fake engine
            database.build_engine(f"sqlite:///{db_path}")

    assert captured["url"].startswith("sqlite:///")
    kwargs = captured["kwargs"]
    assert "pool_size" not in kwargs  # SQLite branch does not pass pool tuning
    assert "max_overflow" not in kwargs
    connect_args = kwargs["connect_args"]
    assert connect_args == {"check_same_thread": False}
    assert "options" not in connect_args


def test_sqlite_engine_enables_foreign_keys_pragma(tmp_path):
    """Real SQLite engine must have foreign_keys=ON so the cascade FK is honoured."""
    db_path = tmp_path / "fk_pragma.db"
    engine = database.build_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()
            assert row is not None
            assert int(row[0]) == 1
    finally:
        engine.dispose()
