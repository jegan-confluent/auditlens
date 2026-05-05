import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services.db_status_service import redact_database_url
from backend.app.services.db_status_service import build_status_payload


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
    assert "source_ip coverage:" in result.stdout
    assert "recent 4h rows:" in result.stdout
    assert "password" not in result.stdout.lower()


def test_redact_database_url_masks_postgres_password():
    redacted = redact_database_url("postgresql://auditlens:supersecret@127.0.0.1:5432/auditlens")
    assert "supersecret" not in redacted
    assert "auditlens:***@" in redacted


def test_db_status_reports_source_ip_coverage(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_coverage.db'}"
    engine = build_engine(db_url)
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            AuditEvent(
                event_fingerprint="coverage-1",
                timestamp=now - timedelta(minutes=10),
                actor="u-1",
                action="kafka.Authentication",
                normalized_action="kafka.Authentication",
                action_category="Data",
                resource_type="unknown",
                resource_name="-",
                resource_display="Unknown",
                summary="coverage",
                raw_payload_json='{"clientIp":"165.1.202.190"}',
                source_ip="165.1.202.190",
            )
        )
        db.add(
            AuditEvent(
                event_fingerprint="coverage-2",
                timestamp=now - timedelta(minutes=5),
                actor="u-2",
                action="kafka.Authentication",
                normalized_action="kafka.Authentication",
                action_category="Data",
                resource_type="unknown",
                resource_name="-",
                resource_display="Unknown",
                summary="coverage",
                raw_payload_json='{"clientIp":"165.1.202.191"}',
                source_ip=None,
            )
        )
        db.commit()

    payload = build_status_payload(api_database_url=db_url, forwarder_database_url=db_url, recent_window_hours=4)
    assert payload["audit_events_rows"] == 2
    assert payload["missing_source_ip_rows"] == 1
    assert payload["source_ip_coverage"] == 50.0
    assert payload["recent_rows"] == 2
    assert payload["recent_missing_source_ip_rows"] == 1
    assert payload["recent_source_ip_coverage"] == 50.0


def test_recent_backfill_runner_requires_database_url():
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("FORWARDER_DATABASE_URL", None)
    result = _run([str(REPO_ROOT / "scripts" / "backfill_recent_source_fields.sh")], env=env)
    assert result.returncode != 0
    assert "DATABASE_URL is required" in result.stderr


def test_recent_backfill_runner_redacts_credentials_and_logs_sqlite(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens_recent_backfill.db'}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["FORWARDER_DATABASE_URL"] = db_url
    env["BACKFILL_DRY_RUN"] = "true"
    env["BACKFILL_HOURS"] = "4"
    env["BACKFILL_LIMIT"] = "10"
    result = _run([str(REPO_ROOT / "scripts" / "backfill_recent_source_fields.sh")], env=env)
    assert result.returncode == 0
    assert "DB mode: sqlite" in result.stdout
    assert "password" not in result.stdout.lower()


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
