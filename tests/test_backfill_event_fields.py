import json
import os
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services.backfill_service import backfill_source_fields_from_raw_payload
from backend.app.services.event_service import create_event


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'auditlens.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def test_source_backfill_dry_run_does_not_update():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "backfill-dry-run",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            event.source_ip = None
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=True)
            db.refresh(event)
            assert result["updated"] == 1
            assert event.source_ip is None
    finally:
        tmp.cleanup()


def test_source_backfill_updates_missing_source_ip_and_context():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "backfill-update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                    "cloudResources": {"scope": {"resources": [{"resourceType": "ENVIRONMENT", "resourceId": "env-abc123"}]}},
                },
            )
            event.source_ip = None
            event.source_context = None
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            db.refresh(event)
            assert result["updated"] == 1
            assert event.source_ip == "165.1.202.190"
            assert event.source_context == "env-abc123"
    finally:
        tmp.cleanup()


def test_source_backfill_invalid_json_does_not_crash():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    event_fingerprint="bad-json",
                    timestamp=datetime.now(timezone.utc),
                    actor="u-bad-json",
                    action="GetStatement",
                    normalized_action="Read/listed",
                    action_category="Data",
                    resource_type="statement",
                    resource_name="stmt",
                    resource_display="Statement: stmt",
                    summary="bad json",
                    raw_payload_json='{"clientIp":"165.1.202.190",',
                )
            )
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            assert result["invalid_json"] == 1
    finally:
        tmp.cleanup()


def test_source_backfill_extracts_top_level_client_ip_from_raw_payload_json():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    event_fingerprint="top-level-client-ip",
                    timestamp=datetime.now(timezone.utc),
                    actor="u-source",
                    action="kafka.Authentication",
                    normalized_action="kafka.Authentication",
                    action_category="Data",
                    resource_type="unknown",
                    resource_name="-",
                    resource_display="Unknown",
                    summary="top level client ip",
                    raw_payload_json='{"clientIp":"165.1.202.190","data_json":"{\\"requestMetadata\\":{\\"clientAddress\\":[{\\"ip\\":\\"165.1.202.190\\"}]}}"}',
                )
            )
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=True)
            event = db.query(AuditEvent).filter_by(event_fingerprint="top-level-client-ip").one()
            assert result["updated"] == 1
            assert event.source_ip is None

            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            event = db.query(AuditEvent).filter_by(event_fingerprint="top-level-client-ip").one()
            assert result["updated"] == 1
            assert event.source_ip == "165.1.202.190"
    finally:
        tmp.cleanup()


def test_source_backfill_extracts_nested_data_json_client_ip():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            db.add(
                AuditEvent(
                    event_fingerprint="nested-data-json-client-ip",
                    timestamp=datetime.now(timezone.utc),
                    actor="u-source",
                    action="kafka.Authentication",
                    normalized_action="kafka.Authentication",
                    action_category="Data",
                    resource_type="unknown",
                    resource_name="-",
                    resource_display="Unknown",
                    summary="nested client ip",
                    raw_payload_json='{"data_json":"{\\"requestMetadata\\":{\\"clientAddress\\":[{\\"ip\\":\\"165.1.202.190\\"}]},\\"clientIp\\":\\"165.1.202.190\\"}"}',
                )
            )
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            event = db.query(AuditEvent).filter_by(event_fingerprint="nested-data-json-client-ip").one()
            assert result["updated"] == 1
            assert event.source_ip == "165.1.202.190"
    finally:
        tmp.cleanup()


def test_source_backfill_hours_applies_timestamp_filter():
    tmp, SessionLocal = _session()
    try:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            old_event = create_event(
                db,
                {
                    "id": "backfill-old",
                    "timestamp": (now - timedelta(hours=6)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            new_event = create_event(
                db,
                {
                    "id": "backfill-new",
                    "timestamp": (now - timedelta(hours=1)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            old_event.source_ip = None
            new_event.source_ip = None
            db.commit()

            result = backfill_source_fields_from_raw_payload(db, dry_run=True, hours=4, limit=10)
            assert result["scanned"] == 1
            assert result["updated"] == 1
    finally:
        tmp.cleanup()


def test_source_backfill_since_until_applies_timestamp_filter():
    tmp, SessionLocal = _session()
    try:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            create_event(
                db,
                {
                    "id": "backfill-before-window",
                    "timestamp": (now - timedelta(hours=10)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            ).source_ip = None
            target_event = create_event(
                db,
                {
                    "id": "backfill-window",
                    "timestamp": (now - timedelta(hours=2)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            target_event.source_ip = None
            create_event(
                db,
                {
                    "id": "backfill-after-window",
                    "timestamp": (now + timedelta(hours=1)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            ).source_ip = None
            db.commit()

            result = backfill_source_fields_from_raw_payload(
                db,
                dry_run=True,
                since=now - timedelta(hours=3),
                until=now - timedelta(hours=1),
                limit=10,
            )
            assert result["scanned"] == 1
            assert result["updated"] == 1
    finally:
        tmp.cleanup()


def test_source_backfill_order_newest_selects_newest_rows_first(capsys):
    tmp, SessionLocal = _session()
    try:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            old_event = create_event(
                db,
                {
                    "id": "backfill-order-old",
                    "timestamp": (now - timedelta(hours=2)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            new_event = create_event(
                db,
                {
                    "id": "backfill-order-new",
                    "timestamp": (now - timedelta(minutes=10)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            old_event.source_ip = None
            new_event.source_ip = None
            db.commit()

            backfill_source_fields_from_raw_payload(db, dry_run=True, order="newest", limit=1, debug_sample=1)
            output = capsys.readouterr().out
            assert f"id={new_event.id}" in output
    finally:
        tmp.cleanup()


def test_source_backfill_does_not_overwrite_without_force():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "backfill-no-overwrite",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": "u-source",
                    "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                },
            )
            event.source_ip = "192.0.2.1"
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            db.refresh(event)
            assert event.source_ip == "192.0.2.1"
            assert result["updated"] >= 0
            result = backfill_source_fields_from_raw_payload(db, dry_run=False, force=True)
            db.refresh(event)
            assert event.source_ip == "165.1.202.190"
            assert result["updated"] == 1
    finally:
        tmp.cleanup()


def test_decision_backfill_dry_run_counts_rows_that_would_be_updated():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "decision-backfill-dry-run",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.DeleteTopics",
                    "resourceType": "Topic",
                    "resourceName": "topic=payments",
                    "summary": "u-admin deleted topic 'payments'",
                },
            )
            event._signal_type = None
            event._signal_reason = None
            event._impact_type = None
            event._risk_level = None
            event._change_type = None
            event._resource_family = None
            event._event_title = None
            event._event_summary = None
            event._decision_reason = None
            event._decision_label = None
            event._recommended_action = None
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=True, source_fields=False, decision_fields=True)
            db.refresh(event)
            assert result["updated"] == 1
            assert result["decision_updated"] == 1
            assert event._signal_type is None
    finally:
        tmp.cleanup()


def test_decision_backfill_updates_missing_fields():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "decision-backfill-update",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.DeleteTopics",
                    "resourceType": "Topic",
                    "resourceName": "topic=payments",
                    "summary": "u-admin deleted topic 'payments'",
                },
            )
            event._signal_type = None
            event._signal_reason = None
            event._impact_type = None
            event._risk_level = None
            event._change_type = None
            event._resource_family = None
            event._event_title = None
            event._event_summary = None
            event._decision_reason = None
            event._decision_label = None
            event._recommended_action = None
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False, source_fields=False, decision_fields=True)
            db.refresh(event)
            assert result["updated"] == 1
            assert result["decision_updated"] == 1
            assert event._signal_type == "action_required"
            assert event._decision_label == "Action Needed"
            assert event._impact_type == "destructive"
    finally:
        tmp.cleanup()


def test_decision_backfill_force_recomputes_existing_fields():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(
                db,
                {
                    "id": "decision-backfill-force",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "methodName": "kafka.DeleteTopics",
                    "resourceType": "Topic",
                    "resourceName": "topic=payments",
                    "summary": "u-admin deleted topic 'payments'",
                },
            )
            event._signal_type = "informational"
            event._signal_reason = "noise"
            event._impact_type = "read_only"
            event._risk_level = "low"
            event._change_type = "read/listed"
            event._resource_family = "topic"
            event._event_title = "Wrong title"
            event._event_summary = "Wrong summary"
            event._decision_reason = "Wrong reason"
            event._decision_label = "Info"
            event._recommended_action = "No action needed"
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False, source_fields=False, decision_fields=True, force=True)
            db.refresh(event)
            assert result["updated"] == 1
            assert result["decision_updated"] == 1
            assert event._signal_type == "action_required"
            assert event._decision_label == "Action Needed"
            assert event._impact_type == "destructive"
    finally:
        tmp.cleanup()


def test_source_backfill_invalid_timestamp_errors_cleanly(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'auditlens-invalid-timestamp.db'}"
    env = {"DATABASE_URL": db_url, "FORWARDER_DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "backfill_event_fields.py"), "--source-fields", "--dry-run", "--since", "not-a-timestamp"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid --since timestamp" in result.stderr
