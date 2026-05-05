import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

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
                    "cloudResources": {"scope": {"resources": [{"resourceType": "ENVIRONMENT", "resourceId": "env-mkr6ww"}]}},
                },
            )
            event.source_ip = None
            event.source_context = None
            db.commit()
            result = backfill_source_fields_from_raw_payload(db, dry_run=False)
            db.refresh(event)
            assert result["updated"] == 1
            assert event.source_ip == "165.1.202.190"
            assert event.source_context == "env-mkr6ww"
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
