from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.db.models import AuditEvent
from backend.app.services import backfill_service
from backend.app.services.backfill_service import backfill_resource_intelligence_from_raw_payload
from backend.app.services.event_service import create_event


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'auditlens.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def _resource_event(timestamp: datetime, *, event_id: str = "resource-backfill") -> dict[str, object]:
    return {
        "id": event_id,
        "timestamp": timestamp.isoformat(),
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-source",
        "resourceName": "crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1/topic=orders",
        "summary": "u-source created topic 'orders'",
        "resultStatus": "Success",
    }


def test_resource_backfill_dry_run_does_not_update():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(db, _resource_event(datetime.now(timezone.utc)))
            event._resource_display_name = "Custom Display"
            event._parent_resource = None
            db.commit()

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=True, limit=10)
            db.refresh(event)

            assert result["updated"] == 1
            assert event._resource_display_name == "Custom Display"
            assert event._parent_resource is None
    finally:
        tmp.cleanup()


def test_resource_backfill_updates_missing_fields():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(db, _resource_event(datetime.now(timezone.utc), event_id="resource-update"))
            event._resource_display_name = None
            event._parent_resource = None
            db.commit()

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=False, limit=10)
            db.refresh(event)

            assert result["updated"] == 1
            assert event._resource_display_name == "Topic: orders"
            assert event._parent_resource is not None
    finally:
        tmp.cleanup()


def test_resource_backfill_does_not_overwrite_without_force():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(db, _resource_event(datetime.now(timezone.utc), event_id="resource-no-force"))
            event._resource_display_name = "Custom Display"
            event._parent_resource = None
            db.commit()

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=False, limit=10)
            db.refresh(event)

            assert result["updated"] == 1
            assert event._resource_display_name == "Custom Display"
            assert event._parent_resource is not None
    finally:
        tmp.cleanup()


def test_resource_backfill_force_overwrites_existing_fields():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(db, _resource_event(datetime.now(timezone.utc), event_id="resource-force"))
            event._resource_display_name = "Custom Display"
            event._parent_resource = None
            db.commit()

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=False, limit=10, force=True)
            db.refresh(event)

            assert result["updated"] == 1
            assert event._resource_display_name == "Topic: orders"
            assert event._parent_resource is not None
    finally:
        tmp.cleanup()


def test_resource_backfill_malformed_payload_does_not_crash():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = AuditEvent(
                event_fingerprint="resource-invalid-json",
                timestamp=datetime.now(timezone.utc),
                result="Success",
                actor="u-source",
                action="CreateTopics",
                normalized_action="CreateTopics",
                action_category="Create",
                resource_type="unknown",
                resource_name="-",
                resource_display="Unknown",
                summary="bad payload",
                raw_payload_json='{"resourceName":"crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1/topic=orders",',
            )
            db.add(event)
            db.commit()

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=False, limit=10)
            db.refresh(event)

            assert result["invalid_json"] == 1
            assert result["updated"] == 0
    finally:
        tmp.cleanup()


def test_resource_backfill_catalog_failure_does_not_rollback_event_update(monkeypatch):
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            event = create_event(db, _resource_event(datetime.now(timezone.utc), event_id="resource-catalog-failure"))
            event._resource_display_name = None
            event._parent_resource = None
            db.commit()

            def failing_upsert(*args, **kwargs):
                raise RuntimeError("catalog down")

            monkeypatch.setattr(backfill_service, "upsert_resource_catalog", failing_upsert)

            result = backfill_resource_intelligence_from_raw_payload(db, dry_run=False, limit=10)
            db.refresh(event)

            assert result["updated"] == 1
            assert result["catalog_failed"] >= 1
            assert event._resource_display_name == "Topic: orders"
            assert event._parent_resource is not None
    finally:
        tmp.cleanup()
