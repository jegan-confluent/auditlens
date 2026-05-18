"""Tests for archive-before-delete guard and batched event delete in cleanup_retention."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services.event_service import cleanup_retention


@pytest.fixture()
def db_session():
    """Fresh SQLite in-memory database for each test."""
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with Session() as db:
        yield db


def _insert_event(db, ts: datetime, fingerprint: str | None = None) -> str:
    fp = fingerprint or str(uuid.uuid4())
    ev = AuditEvent(
        event_fingerprint=fp,
        timestamp=ts,
        result="Success",
        actor="test-actor",
        action="TestAction",
    )
    db.add(ev)
    db.commit()
    return fp


def _count_events(db) -> int:
    return int(db.scalar(select(func.count(AuditEvent.id))) or 0)


# ---------------------------------------------------------------------------
# Test 1 — Delete is skipped when cold storage is enabled and archive fails
# ---------------------------------------------------------------------------

def test_retention_skips_delete_when_archive_fails(db_session):
    """DELETE must not run if cold storage is enabled and archive returns errors."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    _insert_event(db_session, old_ts, "fp-archive-fail")

    archive_returns = {
        "enabled": True,
        "days_archived": 0,
        "bytes_archived": 0,
        "events_archived": 0,
        "errors": ["upload failed for 2024-01-01"],
        "dry_run": False,
    }

    with patch(
        "backend.app.services.event_service.archive_events_before",
        return_value=archive_returns,
    ):
        result = cleanup_retention(db_session, retention_days=7)

    assert result["deleted_count"] == 0, "Must not report deletions when archive fails"
    assert result.get("archive_error") is True, "Must set archive_error=True in result"
    assert _count_events(db_session) == 1, "Row must survive when archive fails"


def test_retention_skips_delete_when_archive_raises(db_session):
    """DELETE must not run if archive_events_before raises unexpectedly."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    _insert_event(db_session, old_ts, "fp-archive-raise")

    with patch(
        "backend.app.services.event_service.archive_events_before",
        side_effect=RuntimeError("S3 connection refused"),
    ):
        result = cleanup_retention(db_session, retention_days=7)

    assert result.get("archive_error") is True
    assert _count_events(db_session) == 1, "Row must survive when archive raises"


# ---------------------------------------------------------------------------
# Test 2 — Normal delete proceeds when cold storage is disabled
# ---------------------------------------------------------------------------

def test_retention_deletes_when_cold_storage_disabled(db_session):
    """Normal delete path runs when cold storage returns enabled=False."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    recent_ts = datetime.now(timezone.utc) - timedelta(days=1)
    _insert_event(db_session, old_ts, "fp-old")
    _insert_event(db_session, recent_ts, "fp-recent")

    archive_returns = {
        "enabled": False,
        "days_archived": 0,
        "bytes_archived": 0,
        "error": None,
    }

    with patch(
        "backend.app.services.event_service.archive_events_before",
        return_value=archive_returns,
    ):
        result = cleanup_retention(db_session, retention_days=7)

    assert result["deleted_count"] == 1, "Old row should be counted as deleted"
    assert result.get("archive_error") is not True
    assert _count_events(db_session) == 1, "Only the recent row should remain"


# ---------------------------------------------------------------------------
# Test 3 — Batch delete handles >1000 eligible rows correctly
# ---------------------------------------------------------------------------

def test_retention_batches_deletes(db_session):
    """With 1500 eligible rows, all are deleted (batch loop runs to completion)."""
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    recent_ts = datetime.now(timezone.utc) - timedelta(days=1)

    for i in range(1500):
        _insert_event(db_session, old_ts, f"fp-batch-old-{i}")
    for i in range(50):
        _insert_event(db_session, recent_ts, f"fp-batch-recent-{i}")

    archive_returns = {"enabled": False, "days_archived": 0, "bytes_archived": 0, "error": None}

    with patch(
        "backend.app.services.event_service.archive_events_before",
        return_value=archive_returns,
    ):
        result = cleanup_retention(db_session, retention_days=7)

    assert result["deleted_count"] == 1500, "All 1500 old rows must be deleted"
    assert _count_events(db_session) == 50, "Only the 50 recent rows should remain"
