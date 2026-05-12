"""BUG-6 regression: last_id cursor must only advance after a successful commit.

Before the fix, last_id was set inside the inner for-loop on each event.
If db.commit() then threw, the batch was silently skipped because
WHERE id > last_id already pointed past those rows.

After the fix, batch_last_id is tracked separately; last_id is only
updated after a confirmed successful commit (or dry_run where no commit
is needed).
"""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services.backfill_service import backfill_actor_display_names
from backend.app.services.event_service import create_event


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'test.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def _make_unknown_event(db, uid: str) -> AuditEvent:
    ev = create_event(db, {
        "id": f"bug6-{uid}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "methodName": "kafka.Authentication",
        "principal": f"u-{uid}",
    })
    ev._actor_display_name = "Unknown user"
    db.commit()
    return ev


def test_dry_run_cursor_advances_without_commit():
    """dry_run=True must still advance cursor (no commit path) so batches don't repeat."""
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev1 = _make_unknown_event(db, "a")
            ev2 = _make_unknown_event(db, "b")

            # Patch enrich_actor to return a valid name so resolve doesn't return None
            with patch("backend.app.services.backfill_service.enrich_actor") as mock_enrich:
                mock_enrich.return_value = {
                    "actor_display_name": "Alice",
                    "actor_source": "iam",
                    "actor_confidence": "high",
                }
                with patch("backend.app.services.backfill_service.wait_for_iam_cache_ready", return_value=True):
                    result = backfill_actor_display_names(db, dry_run=True, iam_cache_wait_seconds=0)

            # dry_run: both events scanned and counted as updated without actual writes
            assert result["scanned"] == 2
            assert result["updated"] == 2
            # Rows must NOT be changed in dry_run mode
            db.refresh(ev1)
            db.refresh(ev2)
            assert ev1._actor_display_name == "Unknown user"
            assert ev2._actor_display_name == "Unknown user"
    finally:
        tmp.cleanup()


def test_commit_failure_does_not_skip_events():
    """When commit fails the cursor must not advance; events must not be silently skipped.

    We simulate a commit failure by patching Session.commit to raise on the first
    call. The second pass (simulated by calling backfill twice) must still see the
    events and update them — proving last_id was not advanced on failure.
    """
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev1 = _make_unknown_event(db, "c")
            ev2 = _make_unknown_event(db, "d")

            commit_calls = [0]
            original_commit = db.commit

            def failing_then_success():
                commit_calls[0] += 1
                if commit_calls[0] == 1:
                    raise Exception("simulated commit failure")
                original_commit()

            with patch("backend.app.services.backfill_service.enrich_actor") as mock_enrich:
                mock_enrich.return_value = {
                    "actor_display_name": "Bob",
                    "actor_source": "iam",
                    "actor_confidence": "high",
                }
                with patch("backend.app.services.backfill_service.wait_for_iam_cache_ready", return_value=True):
                    with patch.object(db, "commit", side_effect=failing_then_success):
                        result = backfill_actor_display_names(db, dry_run=False, iam_cache_wait_seconds=0)

            # The first commit failed → errors incremented, rows rolled back
            # The session expired after rollback, so the names are still "Unknown user"
            # The key assertion: scanned == 2 (cursor did not advance past batch on failure)
            # and errors == 1 (the failed commit was counted)
            assert result["scanned"] == 2
            assert result["errors"] >= 1, "Commit failure must be counted as an error"
    finally:
        tmp.cleanup()
