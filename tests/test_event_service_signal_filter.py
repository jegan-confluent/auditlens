"""Tests that signal_type filtering in list_events_result uses a DB WHERE clause.

Before the fix, signal_type was applied only in Python post-processing with a
5000-row scan cap, so the total was always wrong or misleading.  After the fix,
signal_type is pushed into the SQL WHERE clause (on the indexed _signal_type
column) and the returned total reflects the real row count.
"""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.services.event_service import create_event, list_events_result


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'test.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def _make_event(db, uid: str, signal: str):
    ev = create_event(db, {
        "id": f"sig-filter-{uid}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "methodName": "kafka.Authentication",
        "principal": f"u-{uid}",
    })
    ev._signal_type = signal
    db.commit()
    return ev


def test_signal_type_filter_returns_accurate_total():
    """signal_type filter applied at DB level — total matches real count, not scan cap."""
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "ar1", "action_required")
            _make_event(db, "ar2", "action_required")
            _make_event(db, "at1", "attention")
            _make_event(db, "n1", "noise")

            result = list_events_result(db, signal_type="action_required", mode="audit_trail")
            assert result.signal_filter_applied is True
            assert result.total == 2
            assert len(result.items) == 2
            assert all(ev._signal_type == "action_required" for ev in result.items)

            result_att = list_events_result(db, signal_type="attention", mode="audit_trail")
            assert result_att.total == 1
            assert result_att.signal_filter_applied is True

            result_all = list_events_result(db, mode="audit_trail")
            assert result_all.total == 4
            assert result_all.signal_filter_applied is False
    finally:
        tmp.cleanup()


def test_signal_type_multi_value_uses_in_clause():
    """Comma-separated signal_type values map to SQL IN (...)."""
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "ar1", "action_required")
            _make_event(db, "at1", "attention")
            _make_event(db, "n1", "noise")

            result = list_events_result(db, signal_type="action_required,attention", mode="audit_trail")
            assert result.signal_filter_applied is True
            assert result.total == 2
    finally:
        tmp.cleanup()


def test_signal_type_absent_returns_all_with_flag_false():
    """No signal_type param → signal_filter_applied is False."""
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "ar1", "action_required")
            _make_event(db, "n1", "noise")

            result = list_events_result(db, mode="audit_trail")
            assert result.signal_filter_applied is False
            assert result.total == 2
    finally:
        tmp.cleanup()
