import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.main import create_app
from backend.scripts.seed_data import SEED_EVENTS
from backend.app.services.event_service import cleanup_retention, create_event, upsert_events
from backend.app.core.config import get_settings


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "auditlens.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("FORWARDER_HEALTH_URL", "http://127.0.0.1:9/health")
        monkeypatch.setattr("backend.app.main.init_db", lambda: None)
        get_settings.cache_clear()
        engine = build_engine(f"sqlite:///{db_path}")
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        init_db(engine)
        with TestingSessionLocal() as db:
            for payload in SEED_EVENTS:
                create_event(db, payload)

        app = create_app()

        def override_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        yield TestClient(app)


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database_mode"] == "sqlite"


def test_seeded_data_exists(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json()["total"] == len(SEED_EVENTS)


def test_topic_create_jegan_testing_filter(client):
    response = client.get(
        "/events",
        params={"resource_type": "Topic", "resource": "jegan-testing", "action_category": "Create"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    event = body["items"][0]
    assert event["resource_name"] == "jegan-testing"
    assert event["action_category"] == "Create"
    assert "created topic 'jegan-testing'" in event["summary"]


def test_time_window_accepts_valid_values(client):
    for value in ("5m", "1h", "24h"):
        response = client.get("/events", params={"time_window": value, "limit": 1})
        assert response.status_code == 200


def test_time_window_rejects_invalid_values(client):
    for value in ("", "0m", "-1h", "24d", "not-a-window", "15"):
        response = client.get("/events", params={"time_window": value, "limit": 1})
        assert response.status_code == 422


def test_failures_endpoint_returns_failed_events(client):
    response = client.get("/failures")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert all(item["result"] == "Failure" for item in body["items"])


def test_filters_options_returns_categories(client):
    response = client.get("/filters/options")
    assert response.status_code == 200
    body = response.json()
    assert "Topic" in body["resource_types"]
    assert "Create" in body["action_categories"]
    assert "Delete" in body["action_categories"]
    assert "Security" in body["action_categories"]


def test_pagination_works(client):
    first = client.get("/events", params={"limit": 2, "offset": 0}).json()
    second = client.get("/events", params={"limit": 2, "offset": 2}).json()
    assert first["limit"] == 2
    assert first["offset"] == 0
    assert second["offset"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_pagination_rejects_limit_above_max(client):
    response = client.get("/events", params={"limit": 501})
    assert response.status_code == 422


def test_events_list_excludes_raw_payload_json(client):
    response = client.get("/events", params={"limit": 1})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert "raw_payload_json" not in item


def test_event_detail_includes_raw_payload_json(client):
    event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["id"]
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert "raw_payload_json" in body
    assert body["raw_payload_json"].startswith("{")


def test_summary_aggregates_work(client):
    response = client.get("/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_events"] == len(SEED_EVENTS)
    assert body["failures"] >= 2
    assert body["by_action_category"]["Create"] >= 2
    assert body["by_resource_type"]["Topic"] >= 1


def test_ready_reports_db_health_for_overridden_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["db"]["can_connect"] is True
    assert body["db"]["event_count"] == len(SEED_EVENTS)


def test_live_reports_process_alive(client):
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_system_status_includes_db_health_for_overridden_database(client):
    response = client.get("/system/status")
    assert response.status_code == 200
    body = response.json()
    assert body["database_mode"] == "sqlite"
    assert body["db_health"]["event_count"] == len(SEED_EVENTS)
    assert "storage_usage" in body


def test_batch_upsert_deduplicates_events(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        inserted = upsert_events(db, [SEED_EVENTS[0], SEED_EVENTS[0]])
        total = client.get("/events").json()["total"]
    finally:
        session_gen.close()
    assert inserted == 0
    assert total == len(SEED_EVENTS)


def test_retention_cleanup_dry_run_and_delete(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        create_event(
            db,
            {
                "id": "old-retention-test",
                "timestamp": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
                "actor": "retention-test",
                "methodName": "io.confluent.kafka.server/CreateTopics",
                "resourceName": "crn://confluent.cloud/topic=old-topic",
            },
        )
        dry_run = cleanup_retention(db, 1, dry_run=True)
        deleted = cleanup_retention(db, 1, dry_run=False)
    finally:
        session_gen.close()
    assert dry_run["dry_run"] is True
    assert dry_run["deleted_count"] >= 1
    assert deleted["dry_run"] is False
    assert deleted["deleted_count"] == dry_run["deleted_count"]
