import os
import subprocess
import sys
from pathlib import Path

from backend.app.services.db_status_service import redact_database_url


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd, *, env):
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)


def test_db_status_redacts_credentials_and_reports_sqlite_mode(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_status.db'}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["FORWARDER_DATABASE_URL"] = db_url
    result = _run([str(REPO_ROOT / "scripts" / "db_status.sh")], env=env)
    assert result.returncode == 0
    assert "DB mode: sqlite" in result.stdout
    assert "API DB: sqlite:///" in result.stdout
    assert "Forwarder DB: sqlite:///" in result.stdout
    assert "password" not in result.stdout.lower()


def test_redact_database_url_masks_postgres_password():
    redacted = redact_database_url("postgresql://auditlens:supersecret@127.0.0.1:5432/auditlens")
    assert "supersecret" not in redacted
    assert "auditlens:***@" in redacted


def test_backfill_reports_db_mode_and_refuses_empty_update(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_backfill.db'}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["FORWARDER_DATABASE_URL"] = db_url
    dry_run = _run([sys.executable, str(REPO_ROOT / "scripts" / "backfill_event_fields.py"), "--source-fields", "--dry-run"], env=env)
    assert dry_run.returncode == 0
    assert "DB mode: sqlite" in dry_run.stdout
    assert "audit_events rows: 0" in dry_run.stdout

    update = _run([sys.executable, str(REPO_ROOT / "scripts" / "backfill_event_fields.py"), "--source-fields"], env=env)
    assert update.returncode == 1
    assert "Refusing to update an empty audit_events table" in update.stderr


def test_backfill_allows_explicit_empty_updates(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_backfill_allow.db'}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["FORWARDER_DATABASE_URL"] = db_url
    result = _run(
        [sys.executable, str(REPO_ROOT / "scripts" / "backfill_event_fields.py"), "--source-fields", "--allow-empty", "--dry-run"],
        env=env,
    )
    assert result.returncode == 0
    assert "DB mode: sqlite" in result.stdout
