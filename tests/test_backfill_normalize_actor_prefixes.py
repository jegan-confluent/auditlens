"""FIX 2: backfill_normalize_actor_prefixes strips User:u- / User:sa- prefixes.

Tests:
  - User:u-xxxxx actor is corrected to u-xxxxx
  - User:sa-xxxxx actor is corrected to sa-xxxxx
  - User:NNNN (numeric) is NOT touched
  - Already-normalized rows (u-xxxxx) are NOT touched
  - dry_run=True returns correct count but makes no changes
"""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services.backfill_service import backfill_normalize_actor_prefixes
from backend.app.services.event_service import create_event


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'test.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def _make_event(db, uid: str, actor: str) -> AuditEvent:
    ev = create_event(db, {
        "id": f"prefix-test-{uid}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "methodName": "kafka.TestEvent",
        "principal": actor,
        "principal_normalized": actor,
    })
    # Override actor directly to simulate pre-fix stored rows
    ev.actor = actor
    ev.actor_id = actor
    db.commit()
    return ev


def test_strips_user_u_prefix():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev = _make_event(db, "u1", "User:u-zmknkp7")
            result = backfill_normalize_actor_prefixes(db, dry_run=False)
            db.refresh(ev)
            assert ev.actor == "u-zmknkp7"
            assert result["updated"] >= 1
    finally:
        tmp.cleanup()


def test_strips_user_sa_prefix():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev = _make_event(db, "sa1", "User:sa-8nwyn7")
            result = backfill_normalize_actor_prefixes(db, dry_run=False)
            db.refresh(ev)
            assert ev.actor == "sa-8nwyn7"
            assert result["updated"] >= 1
    finally:
        tmp.cleanup()


def test_does_not_touch_numeric_user_prefix():
    """User:3958188 must NOT be stripped — needs principalResourceId resolution."""
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev = _make_event(db, "num1", "User:3958188")
            result = backfill_normalize_actor_prefixes(db, dry_run=False)
            db.refresh(ev)
            assert ev.actor == "User:3958188"
            assert result["updated"] == 0
    finally:
        tmp.cleanup()


def test_does_not_touch_already_normalized():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev = _make_event(db, "clean1", "u-zmknkp7")
            result = backfill_normalize_actor_prefixes(db, dry_run=False)
            db.refresh(ev)
            assert ev.actor == "u-zmknkp7"
            assert result["updated"] == 0
    finally:
        tmp.cleanup()


def test_dry_run_reports_count_without_changes():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "dry1", "User:u-aaa111")
            _make_event(db, "dry2", "User:sa-bbb222")
            result = backfill_normalize_actor_prefixes(db, dry_run=True)
            assert result["updated"] == 2
            assert result["dry_run"] is True
            # Actors must still carry the prefix — no changes committed
            from sqlalchemy import text
            count = db.execute(
                text("SELECT COUNT(*) FROM audit_events WHERE actor LIKE 'User:u-%' OR actor LIKE 'User:sa-%'")
            ).scalar()
            assert count == 2
    finally:
        tmp.cleanup()
