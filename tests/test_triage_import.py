import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEventTriage
from backend.app.services.event_service import create_event
from backend.app.services.triage_service import get_triage_record


REPO_ROOT = Path(__file__).resolve().parents[1]


def _session(db_url: str):
    engine = build_engine(db_url)
    init_db(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _run_import(env, *args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "import_triage_state.py"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_triage_import_dry_run_and_actual_run(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_triage.db'}"
    triage_file = tmp_path / "triage_state.json"
    SessionLocal = _session(db_url)
    with SessionLocal() as db:
        event = create_event(
            db,
            {
                "id": "triage-import-event",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "kafka.DeleteTopics",
                "resourceType": "Topic",
                "resourceName": "topic=payments",
                "summary": "u-admin deleted topic 'payments'",
            },
        )
        fingerprint = event.event_fingerprint
    triage_file.write_text(
        json.dumps(
            {
                fingerprint: {
                    "triage_status": "approved",
                    "triage_actor": "legacy",
                    "triage_note": "approved by change ticket",
                    "triage_timestamp": "2026-05-06T10:00:00Z",
                },
                "1": {"triage_status": "resolved"},
            },
            indent=2,
            sort_keys=True,
        )
    )
    env = {**os.environ, "DATABASE_URL": db_url, "FORWARDER_DATABASE_URL": db_url, "TRIAGE_STATE_FILE": str(triage_file)}

    dry_run = _run_import(env, "--dry-run")
    assert dry_run.returncode == 0
    payload = json.loads(dry_run.stdout.strip())
    assert payload["scanned_entries"] == 2
    assert payload["matched_entries"] == 1
    assert payload["imported"] == 1
    assert payload["skipped_stale"] == 1
    with SessionLocal() as db:
        assert get_triage_record(db, fingerprint) is None

    apply_run = _run_import(env)
    assert apply_run.returncode == 0
    payload = json.loads(apply_run.stdout.strip())
    assert payload["imported"] == 1
    assert payload["updated"] == 0
    with SessionLocal() as db:
        stored = db.query(AuditEventTriage).filter(AuditEventTriage.event_fingerprint == fingerprint).one()
        assert stored.triage_status == "approved"
        assert stored.triage_actor == "legacy"
        assert stored.triage_note == "approved by change ticket"
        assert stored.triage_source == "file_import"


def test_triage_import_respects_force_and_skips_existing_without_it(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_triage_force.db'}"
    triage_file = tmp_path / "triage_state_force.json"
    SessionLocal = _session(db_url)
    with SessionLocal() as db:
        event = create_event(
            db,
            {
                "id": "triage-force-event",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "kafka.DeleteTopics",
                "resourceType": "Topic",
                "resourceName": "topic=payments",
                "summary": "u-admin deleted topic 'payments'",
            },
        )
        fingerprint = event.event_fingerprint

    triage_file.write_text(
        json.dumps(
            {
                fingerprint: {
                    "triage_status": "resolved",
                    "triage_actor": "file-import",
                    "triage_note": "resolved in file",
                    "triage_timestamp": "2026-05-06T12:00:00Z",
                }
            }
        )
    )
    env = {**os.environ, "DATABASE_URL": db_url, "FORWARDER_DATABASE_URL": db_url, "TRIAGE_STATE_FILE": str(triage_file)}

    with SessionLocal() as db:
        db.add(
            AuditEventTriage(
                event_fingerprint=fingerprint,
                triage_status="approved",
                triage_actor="api",
                triage_note="existing",
                triage_source="api",
            )
        )
        db.commit()

    no_force = _run_import(env, "--dry-run")
    assert no_force.returncode == 0
    payload = json.loads(no_force.stdout.strip())
    assert payload["skipped_existing"] == 1
    with SessionLocal() as db:
        stored = get_triage_record(db, fingerprint)
        assert stored is not None
        assert stored.triage_status == "approved"

    forced = _run_import(env, "--force")
    assert forced.returncode == 0
    payload = json.loads(forced.stdout.strip())
    assert payload["updated"] == 1
    with SessionLocal() as db:
        stored = get_triage_record(db, fingerprint)
        assert stored is not None
        assert stored.triage_status == "resolved"
