import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, get_db, init_db
from backend.app.db.models import AuditEventTriage, ResourceCatalog
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
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_seeded_data_exists(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json()["total"] == len(SEED_EVENTS) - 2


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


def test_resource_type_filter_accepts_uppercase_and_returns_canonical(client):
    response = client.get("/events", params={"resource_type": "TOPIC", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert all(item["resource_type"] == "topic" for item in body["items"])


def test_events_and_summary_use_persisted_decision_fields(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        event = create_event(
            db,
            {
                "id": "persisted-decision-fields",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "kafka.CreateTopics",
                "action": "CreateTopics",
                "user": "u-persisted",
                "resourceType": "Topic",
                "resourceName": "topic=persisted-topic",
                "summary": "u-persisted created topic 'persisted-topic'",
                "resultStatus": "Success",
            },
        )
        event._signal_type = "attention"
        event._signal_reason = "config_changed"
        event._impact_type = "configuration_change"
        event._risk_level = "medium"
        event._change_type = "updated"
        event._resource_family = "topic"
        event._event_title = "Persisted topic update"
        event._event_summary = "Persisted topic update summary"
        event._decision_reason = "Persisted decision reason"
        event._decision_label = "Review"
        event._recommended_action = "Review persisted update"
        db.commit()
    finally:
        session_gen.close()

    response = client.get("/events", params={"mode": "decision", "actor": "u-persisted", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["signal_type"] == "attention"
    assert item["decision_label"] == "Review"
    assert item["event_title"] == "Persisted topic update"
    assert item["event_summary"] == "Persisted topic update summary"

    summary = client.get("/summary", params={"mode": "decision", "actor": "u-persisted"})
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["total_events"] == 1
    assert summary_body["attention_count"] == 1
    assert summary_body["top_actions"][0]["value"] == "Persisted topic update"


def test_resource_type_filter_finds_derived_rows_before_limit(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        for idx in range(60):
            create_event(
                db,
                {
                    "id": f"newer-noise-{idx}",
                    "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=idx)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "resourceType": "CLUSTER",
                    "principal": f"sa-noise-{idx}",
                },
            )
        create_event(
            db,
            {
                "id": "older-topic-delete-before-limit",
                "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                "methodName": "kafka.DeleteTopics",
                "resourceType": "TOPIC",
                "resourceName": "topic=older-topic-delete-before-limit",
            },
        )
    finally:
        session_gen.close()

    response = client.get("/events", params={"resource_type": "TOPIC", "impact_type": "destructive", "limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert body["items"][0]["resource_name"] == "older-topic-delete-before-limit"


def test_time_window_accepts_valid_values(client):
    for value in ("5m", "1h", "24h"):
        response = client.get("/events", params={"time_window": value, "limit": 1})
        assert response.status_code == 200


def test_time_window_rejects_invalid_values(client):
    for value in ("", "0m", "-1h", "24d", "not-a-window", "15"):
        response = client.get("/events", params={"time_window": value, "limit": 1})
        assert response.status_code == 422


def test_mode_decision_hides_routine_reads_but_keeps_mutations_and_failures(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        create_event(
            db,
            {
                "id": "mode-read-1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "ListOrganizations",
                "action": "ListOrganizations",
                "user": "u-org-reader",
                "resourceType": "Organization",
                "resourceName": "organization=o-1",
                "summary": "u-org-reader listed organization 'o-1'",
                "resultStatus": "Success",
            },
        )
        create_event(
            db,
            {
                "id": "mode-delete-1",
                "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                "methodName": "kafka.DeleteTopics",
                "action": "DeleteTopics",
                "user": "u-admin-delete",
                "resourceType": "Topic",
                "resourceName": "topic=payments",
                "summary": "u-admin-delete deleted topic 'payments'",
                "resultStatus": "Success",
            },
        )
        create_event(
            db,
            {
                "id": "mode-create-1",
                "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
                "methodName": "kafka.CreateTopics",
                "action": "CreateTopics",
                "user": "u-admin-create",
                "resourceType": "Topic",
                "resourceName": "topic=orders",
                "summary": "u-admin-create created topic 'orders'",
                "resultStatus": "Success",
            },
        )
        create_event(
            db,
            {
                "id": "mode-failure-1",
                "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat(),
                "methodName": "GetStatement",
                "action": "GetStatement",
                "user": "u-failed-reader",
                "resourceType": "Statement",
                "resourceName": "statement=missing-statement",
                "summary": "u-failed-reader failed to read statement 'missing-statement'",
                "resultStatus": "404 NOT_FOUND",
            },
        )
        create_event(
            db,
            {
                "id": "mode-denied-1",
                "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat(),
                "methodName": "kafka.Authorize",
                "action": "Authorize",
                "user": "u-failed-denied",
                "resourceType": "Topic",
                "resourceName": "topic=restricted",
                "summary": "u-failed-denied was denied access to topic 'restricted'",
                "resultStatus": "Denied",
                "granted": False,
            },
        )
    finally:
        session_gen.close()

    decision_read = client.get("/events", params={"mode": "decision", "actor": "u-org-reader", "limit": 10})
    assert decision_read.status_code == 200
    assert decision_read.json()["total"] == 0

    audit_read = client.get("/events", params={"mode": "audit_trail", "actor": "u-org-reader", "limit": 10})
    assert audit_read.status_code == 200
    assert audit_read.json()["total"] == 1

    decision_delete = client.get("/events", params={"mode": "decision", "actor": "u-admin-delete", "limit": 10})
    assert decision_delete.status_code == 200
    assert decision_delete.json()["total"] == 1

    decision_create = client.get("/events", params={"mode": "decision", "actor": "u-admin-create", "limit": 10})
    assert decision_create.status_code == 200
    assert decision_create.json()["total"] == 1

    decision_failure = client.get("/events", params={"mode": "decision", "actor": "u-failed-reader", "limit": 10})
    assert decision_failure.status_code == 200
    assert decision_failure.json()["total"] == 1

    decision_denied = client.get("/events", params={"mode": "decision", "actor": "u-failed-denied", "limit": 10})
    assert decision_denied.status_code == 200
    assert decision_denied.json()["total"] == 1

    summary_read_decision = client.get("/summary", params={"mode": "decision", "actor": "u-org-reader"})
    summary_read_audit = client.get("/summary", params={"mode": "audit_trail", "actor": "u-org-reader"})
    assert summary_read_decision.status_code == 200
    assert summary_read_audit.status_code == 200
    assert summary_read_decision.json()["total_events"] == 0
    assert summary_read_audit.json()["total_events"] == 1


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
    assert "topic" in body["resource_types"]
    assert "subject" in body["resource_types"]
    assert "connector" in body["resource_types"]
    assert "role_binding" in body["resource_types"]
    assert "environment" in body["resource_types"]
    assert "Create" in body["action_categories"]
    assert "Delete" in body["action_categories"]
    assert "Security" in body["action_categories"]


def test_events_debug_mode_reports_filter_counts_and_distribution(client):
    response = client.get("/events", params={"resource_type": "TOPIC", "debug": "true", "limit": 5})
    assert response.status_code == 200
    debug = response.json()["debug"]
    assert debug["applied_filters"]["resource_type"] == "TOPIC"
    assert debug["row_count_before_derived_filtering"] >= debug["row_count_after_derived_filtering"]
    assert "topic" in debug["resource_type_distribution"]


def test_events_performance_sanity_bounded_scan_for_derived_filters(client):
    response = client.get("/events", params={"hide_noise": "true", "signal_type": "attention,action_required", "limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["scanned_events"] <= 5000


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
    assert "source_display" not in item
    assert "client_id" not in item
    assert "connection_id" not in item
    assert "request_id" not in item


def test_events_list_does_not_access_raw_payload_json(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        create_event(
            db,
            {
                "id": "raw-access-guard",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "kafka.Authentication",
                "principal": "u-raw-guard",
                "data_json": '{"requestMetadata":{"clientAddress":[{"ip":"203.0.113.55"}],"clientId":"client-from-raw"}}',
            },
        )
    finally:
        session_gen.close()

    response = client.get("/events", params={"mode": "audit_trail", "actor": "u-raw-guard", "limit": 1})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["source_context"] == "Not provided by audit event"
    assert "raw_payload_json" not in item
    assert "client_id" not in item


def test_events_include_actor_enrichment_fields(client, monkeypatch):
    monkeypatch.setenv(
        "ACTOR_IDENTITY_MAP_JSON",
        '{"u-75rw9o":{"display_name":"Jegan Admin","email":"jegan@example.com","type":"user"}}',
    )
    from src.product.actor_enrichment import _identity_map, clear_actor_enrichment_cache

    _identity_map.cache_clear()
    clear_actor_enrichment_cache()
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        create_event(
            db,
            {
                "id": "actor-map-regression",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "kafka.CreateTopics",
                "principal": "u-75rw9o",
                "resourceName": "topic=actor-map-regression",
            },
        )
    finally:
        session_gen.close()

    response = client.get("/events", params={"resource": "actor-map-regression", "limit": 1})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["actor_display_name"] == "Jegan Admin"
    assert item["actor_email"] == "jegan@example.com"
    assert item["actor_type"] == "user"
    assert item["actor_raw_id"] == "u-75rw9o"


def test_events_source_display_uses_client_ip_not_cluster_id(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        created = create_event(
            db,
            {
                "id": "source-ip-regression",
                "clientIp": "134.238.241.34",
                "cluster_id": "lkc-k9382g",
                "methodName": "kafka.DeleteTopics",
                "resourceName": "topic=source-ip-regression",
            },
        )
        event_id = created.id
    finally:
        session_gen.close()

    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["source_ip"] == "134.238.241.34"
    assert body["source_display"] == "134.238.241.34"
    assert body["source_display"] != "lkc-k9382g"
    assert body["cluster_id"] == "lkc-k9382g"


def test_events_list_uses_persisted_source_ip_for_request_metadata(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        created = create_event(
            db,
            {
                "id": "source-ip-list-request-metadata",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
                "methodName": "GetStatement",
                "principal": "u-0jwz56",
                "cloudResources": {
                    "scope": {"resources": [{"resourceType": "ENVIRONMENT", "resourceId": "env-mkr6ww"}, {"resourceType": "FLINK_REGION", "resourceId": "aws.us-east-1"}]},
                    "resource": {"resourceType": "STATEMENT", "resourceId": "c360-loyalty-revenue-job"},
                },
            },
        )
        event_id = created.id
    finally:
        session_gen.close()

    list_response = client.get("/events", params={"mode": "audit_trail", "resource": "c360-loyalty-revenue-job", "limit": 1})
    assert list_response.status_code == 200
    item = list_response.json()["items"][0]
    assert item["source_ip"] == "165.1.202.190"
    assert item["source_context"] == "env-mkr6ww"
    assert item["resource_type"] == "statement"
    assert item["resource_name"] == "c360-loyalty-revenue-job"
    assert item["flink_region"] == "aws.us-east-1"
    assert "raw_payload_json" not in item

    detail_response = client.get(f"/events/{event_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["source_ip"] == "165.1.202.190"
    assert detail["source_display"] == "165.1.202.190"


def test_events_include_resource_intelligence_fields_and_catalog_entry(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        created = create_event(
            db,
            {
                "id": "resource-intelligence-regression",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "methodName": "GetStatement",
                "principal": "u-0jwz56",
                "cloudResources": {
                    "scope": {
                        "resources": [
                            {"resourceType": "ORGANIZATION", "resourceId": "org-1"},
                            {"resourceType": "ENVIRONMENT", "resourceId": "env-mkr6ww"},
                            {"resourceType": "FLINK_REGION", "resourceId": "aws.us-east-1"},
                        ]
                    },
                    "resource": {"resourceType": "STATEMENT", "resourceId": "c360-loyalty-revenue-job"},
                },
                "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
            },
        )
        event_id = created.id
        catalog_rows = db.query(ResourceCatalog).filter(ResourceCatalog.resource_name == "c360-loyalty-revenue-job").all()
    finally:
        session_gen.close()

    assert catalog_rows

    response = client.get("/events", params={"mode": "audit_trail", "resource": "c360-loyalty-revenue-job", "limit": 1})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["resource_display_name"] == "Statement: c360-loyalty-revenue-job"
    assert item["resource_scope"].startswith("environment:env-mkr6ww")
    assert item["resource_criticality"] == "medium"
    assert item["blast_radius_hint"] == "environment-scoped"

    detail_response = client.get(f"/events/{event_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["resource_display_name"] == "Statement: c360-loyalty-revenue-job"
    assert detail["parent_resource"] == "environment:env-mkr6ww"
    assert detail["resource_scope"].startswith("environment:env-mkr6ww")


def test_event_triage_lifecycle_basic(client, monkeypatch, tmp_path):
    event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["id"]
    before = client.get(f"/events/{event_id}").json()
    assert before["triage_status"] == "open"

    updated = client.post(
        f"/events/{event_id}/triage",
        json={"triage_status": "approved", "triage_note": "change ticket approved"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["triage_status"] == "approved"
    assert body["triage_note"] == "change ticket approved"
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        stored = db.query(AuditEventTriage).filter(AuditEventTriage.event_fingerprint == before["event_fingerprint"]).one()
        assert stored.triage_status == "approved"
        assert stored.triage_note == "change ticket approved"
        assert stored.triage_source == "api"
    finally:
        session_gen.close()


def test_event_triage_does_not_follow_old_numeric_ids(client, monkeypatch, tmp_path):
    monkeypatch.setenv("TRIAGE_STATE_FILE", str(tmp_path / "triage.json"))
    triage_file = tmp_path / "triage.json"
    triage_file.write_text(json.dumps({"1": {"triage_status": "approved", "triage_actor": "legacy", "triage_note": "legacy id"}}))
    response = client.get("/events", params={"limit": 1})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["triage_status"] == "open"


def test_event_detail_redacts_raw_payload_json_for_non_admin(client):
    event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["id"]
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert "raw_payload_json" in body
    assert body["raw_payload_json"] is None


def test_event_detail_includes_raw_payload_json_for_admin(client, monkeypatch):
    event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["id"]
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "admin-token", "actor_id": "admin", "role": "admin"},
        ]),
    )
    response = client.get(f"/events/{event_id}", headers={"Authorization": "Bearer admin-token"})
    assert response.status_code == 200
    body = response.json()
    assert "raw_payload_json" in body
    assert body["raw_payload_json"].startswith("{")


def test_summary_aggregates_work(client):
    response = client.get("/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_events"] == len(SEED_EVENTS) - 2
    assert body["summary_scope"] == "complete"
    assert body["scanned_events"] == len(SEED_EVENTS) - 2
    assert body["sample_limit"] == 5000
    assert body["failures"] >= 2
    assert body["by_action_category"]["Create"] >= 2
    assert body["by_resource_type"]["topic"] >= 1


def test_events_signal_type_filter_returns_matching_events(client):
    response = client.get("/events", params={"signal_type": "action_required", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["signal_filter_applied"] is True
    assert body["scanned_events"] >= len(body["items"])
    assert body["items"]
    assert all(item["signal_type"] == "action_required" for item in body["items"])


def test_events_signal_type_attention_filter_returns_matching_events(client):
    response = client.get("/events", params={"signal_type": "attention", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["signal_filter_applied"] is True
    assert all(item["signal_type"] == "attention" for item in body["items"])


def test_events_hide_noise_excludes_noise(client):
    response = client.get("/events", params={"hide_noise": "true", "limit": 20})
    assert response.status_code == 200
    body = response.json()
    assert body["hide_noise_applied"] is True
    assert all(item["signal_type"] != "noise" for item in body["items"])


def test_summary_hide_noise_is_consistent_with_events(client):
    events = client.get("/events", params={"time_window": "2h", "hide_noise": "true", "limit": 100})
    summary = client.get("/summary", params={"time_window": "2h", "hide_noise": "true"})
    assert events.status_code == 200
    assert summary.status_code == 200
    event_body = events.json()
    summary_body = summary.json()
    assert event_body["total"] == summary_body["total_events"]
    assert summary_body["noise_count"] == 0
    assert all(item["signal_type"] != "noise" for item in event_body["items"])


def test_events_impact_type_filter_returns_destructive_events(client):
    response = client.get("/events", params={"time_window": "2h", "impact_type": "destructive", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    assert all(item["impact_type"] == "destructive" for item in body["items"])


def test_events_and_summary_agree_for_destructive_filter_before_scan_limit(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    try:
        db = next(session_gen)
        for idx in range(80):
            create_event(
                db,
                {
                    "id": f"summary-newer-noise-{idx}",
                    "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=idx)).isoformat(),
                    "methodName": "kafka.Authentication",
                    "principal": f"sa-summary-noise-{idx}",
                },
            )
        create_event(
            db,
            {
                "id": "summary-older-delete",
                "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
                "methodName": "kafka.DeleteTopics",
                "resourceName": "topic=summary-older-delete",
                "resourceType": "TOPIC",
            },
        )
    finally:
        session_gen.close()

    events = client.get("/events", params={"impact_type": "destructive", "hide_noise": "true", "limit": 100})
    summary = client.get("/summary", params={"impact_type": "destructive", "hide_noise": "true"})
    assert events.status_code == 200
    assert summary.status_code == 200
    event_body = events.json()
    summary_body = summary.json()
    assert any(item["resource_name"] == "summary-older-delete" for item in event_body["items"])
    assert summary_body["total_events"] == event_body["total"]
    assert summary_body["destructive_count"] == event_body["total"]


def test_events_latest_mode_filters_include_destructive_delete(client):
    response = client.get(
        "/events",
        params={"time_window": "2h", "hide_noise": "true", "signal_type": "attention,action_required", "limit": 20},
    )
    assert response.status_code == 200
    body = response.json()
    deletes = [item for item in body["items"] if item["impact_type"] == "destructive" and item["resource_name"] == "old-topic"]
    assert deletes
    assert deletes[0]["signal_type"] == "action_required"


def test_events_stable_newest_first_ordering(client):
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    shared_timestamp = datetime.now(timezone.utc).isoformat()
    try:
        db = next(session_gen)
        first = create_event(
            db,
            {
                "id": "same-ts-a",
                "timestamp": shared_timestamp,
                "methodName": "kafka.CreateTopics",
                "resourceName": "topic=same-ts-a",
                "resourceType": "Topic",
            },
        )
        second = create_event(
            db,
            {
                "id": "same-ts-b",
                "timestamp": shared_timestamp,
                "methodName": "kafka.CreateTopics",
                "resourceName": "topic=same-ts-b",
                "resourceType": "Topic",
            },
        )
        first_id = first.id
        second_id = second.id
    finally:
        session_gen.close()

    response = client.get("/events", params={"limit": 2})
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [second_id, first_id]


def test_events_existing_filters_work_with_signal_type(client):
    response = client.get(
        "/events",
        params={"resource_type": "Topic", "resource": "jegan-testing", "signal_type": "attention,action_required"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["signal_filter_applied"] is True
    assert body["items"]
    assert all(item["resource_type"] == "topic" for item in body["items"])
    assert all(item["signal_type"] in {"attention", "action_required"} for item in body["items"])


def test_events_invalid_signal_type_returns_400(client):
    response = client.get("/events", params={"signal_type": "urgent"})
    assert response.status_code == 400


def test_ready_reports_db_health_for_overridden_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["db"]["can_connect"] is True
    assert body["db"]["event_count"] == len(SEED_EVENTS)
    assert body["components"]["db"] == "ready"


def test_ready_reports_ready_when_db_and_ingestion_are_ready(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.routes.readiness.get_forwarder_status",
        lambda: {
            "consumer_state": "connected",
            "db_writer_enabled": True,
            "db_writer_state": "connected",
            "db_last_successful_write": "2026-04-29T00:00:00Z",
            "db_write_error_total": 0,
            "last_error": None,
        },
    )
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["db"]["can_connect"] is True
    assert body["db"]["event_count"] == len(SEED_EVENTS)


def test_pipeline_ready_reports_degraded_when_forwarder_unavailable(client):
    response = client.get("/pipeline/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["db"] == "ready"
    assert body["components"]["forwarder"] == "degraded"


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
    assert total == len(SEED_EVENTS) - 2


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


def test_admin_retention_cleanup_allows_dev_mode(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    response = client.post("/admin/retention/cleanup", params={"dry_run": "true"})
    assert response.status_code == 200
    assert response.json()["dry_run"] is True


def test_admin_retention_cleanup_requires_admin_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "viewer-token", "actor_id": "viewer", "role": "viewer"},
            {"token": "admin-token", "actor_id": "admin", "role": "admin"},
        ]),
    )

    missing = client.post("/admin/retention/cleanup", params={"dry_run": "true"})
    viewer = client.post(
        "/admin/retention/cleanup",
        params={"dry_run": "true"},
        headers={"Authorization": "Bearer viewer-token"},
    )
    admin = client.post(
        "/admin/retention/cleanup",
        params={"dry_run": "true"},
        headers={"Authorization": "Bearer admin-token"},
    )

    assert missing.status_code == 401
    assert viewer.status_code == 403
    assert admin.status_code == 200
