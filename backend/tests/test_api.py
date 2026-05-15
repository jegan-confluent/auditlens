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
        # Wipe the cross-test in-process caches so each test starts fresh.
        from backend.app.services.system_service import reset_forwarder_health_cache
        from backend.app.services.filter_options_service import clear_filter_options_cache
        from backend.app.core.limiter import limiter

        reset_forwarder_health_cache()
        clear_filter_options_cache()
        # Disable rate limiting for the general fixture; the dedicated rate-limit
        # test re-enables it explicitly. Keeps existing tests free to make many
        # GET /events calls without hitting 429.
        limiter.enabled = False
        limiter.reset()
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
    from backend.app.services.filter_options_service import clear_filter_options_cache

    clear_filter_options_cache()
    response = client.get("/filters/options")
    assert response.status_code == 200
    body = response.json()
    # BUG-31 fix: resource_types now reflects only what exists in the DB,
    # not a hardcoded union with a fixed set of Confluent types.
    assert "topic" in body["resource_types"]
    assert "Create" in body["action_categories"]
    assert "Delete" in body["action_categories"]
    assert "Security" in body["action_categories"]


def test_filters_options_caps_and_caches(client):
    """Filter dropdowns must cap at 500 items and skip the DB on a hit within TTL."""
    from backend.app.services import filter_options_service
    from backend.app.services.filter_options_service import (
        FILTER_OPTIONS_LIMIT,
        clear_filter_options_cache,
        reset_db_call_counter,
    )

    clear_filter_options_cache()

    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        # Seed 600 distinct actor strings to exercise the cap.
        for idx in range(600):
            create_event(
                db,
                {
                    "id": f"actor-cap-{idx}",
                    "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=idx)).isoformat(),
                    "actor": f"sa-cap-{idx}",
                    "methodName": "kafka.Authentication",
                    "principal": f"sa-cap-{idx}",
                },
            )
    finally:
        session_gen.close()

    clear_filter_options_cache()
    reset_db_call_counter()

    first = client.get("/filters/options")
    assert first.status_code == 200
    body = first.json()
    assert len(body["actors"]) <= FILTER_OPTIONS_LIMIT
    assert len(body["actors"]) >= 1

    first_call_count = sum(filter_options_service._db_call_counter.values())
    assert first_call_count > 0  # actually queried the DB

    second = client.get("/filters/options")
    assert second.status_code == 200
    second_call_count = sum(filter_options_service._db_call_counter.values())
    assert second_call_count == first_call_count, (
        "second /filters/options call within TTL should be served from cache without hitting the DB"
    )

    # Mutating the cache TTL or clearing makes the next call hit the DB again.
    clear_filter_options_cache()
    third = client.get("/filters/options")
    assert third.status_code == 200
    third_call_count = sum(filter_options_service._db_call_counter.values())
    assert third_call_count > second_call_count


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


def test_keyset_pagination_first_page_returns_next_cursor(client):
    """When the first page is full, the response carries a non-null next_cursor."""
    response = client.get("/events", params={"mode": "audit_trail", "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"], "expected non-null next_cursor on a full page"


def test_keyset_pagination_walks_pages_without_overlap(client):
    """Walking pages via next_cursor returns disjoint results that cover the entire set."""
    seen: list[int] = []
    cursor: str | None = None
    page_size = 3
    for _ in range(20):  # safety cap
        params = {"mode": "audit_trail", "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/events", params=params)
        assert response.status_code == 200
        body = response.json()
        page_ids = [item["id"] for item in body["items"]]
        # No overlap between consecutive pages.
        assert not (set(page_ids) & set(seen)), f"overlap detected: {page_ids} vs {seen}"
        seen.extend(page_ids)
        cursor = body["next_cursor"]
        if cursor is None:
            break

    # We should have iterated through every audit_trail event exactly once.
    full = client.get("/events", params={"mode": "audit_trail", "limit": 500}).json()
    expected_ids = [item["id"] for item in full["items"]]
    assert sorted(seen) == sorted(expected_ids)


def test_keyset_pagination_last_page_returns_null_cursor(client):
    """The final partial page must carry next_cursor = null."""
    full = client.get("/events", params={"mode": "audit_trail", "limit": 500}).json()
    total = len(full["items"])
    assert total >= 1
    # Use a page_size larger than the total set so the response is the last page.
    response = client.get("/events", params={"mode": "audit_trail", "limit": total + 5})
    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None


def test_keyset_pagination_rejects_malformed_cursor(client):
    response = client.get("/events", params={"mode": "audit_trail", "cursor": "not-a-real-cursor"})
    assert response.status_code == 400


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


def test_event_detail_includes_raw_payload_when_auth_disabled(client):
    # BUG-3 fix: when auth is disabled (dev mode) raw_payload_json is NOT
    # redacted — there are no access controls in effect so all callers see it.
    # Previously this was wrongly returning None even in dev mode.
    event_id = client.get("/events", params={"limit": 1}).json()["items"][0]["id"]
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert "raw_payload_json" in body
    # raw payload is visible when auth is disabled
    assert body["raw_payload_json"] is not None


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


def test_pipeline_ready_uses_cached_forwarder_health_when_upstream_is_slow(client, monkeypatch):
    """Readiness probe must return fast even when the upstream forwarder is slow.

    We seed the cache with a healthy snapshot, then patch httpx.get to sleep
    2 seconds. Because the cache is hit before any HTTP call is made, the
    request should still return well under 100 ms.
    """
    import time as _time

    from backend.app.services import system_service

    # Pre-warm the cache with a healthy snapshot so the route never reaches
    # the (mocked-slow) httpx path.
    system_service._forwarder_health_cache.prime(
        {
            "consumer_state": "connected",
            "last_successful_poll": "2026-05-07T00:00:00Z",
            "retry_count": 0,
            "consecutive_error_count": 0,
            "last_error": None,
            "consumer_lag": 0,
            "records_consumed_total": 100,
            "db_writer_enabled": True,
            "db_writer_state": "connected",
            "db_write_success_total": 100,
            "db_write_error_total": 0,
            "db_write_batch_size": 50,
            "db_last_successful_write": "2026-05-07T00:00:00Z",
            "db_last_error": None,
            "db_last_cleanup_at": None,
            "db_last_cleanup_deleted_count": 0,
        }
    )

    def slow_get(*args, **kwargs):  # pragma: no cover - safety net assertion
        _time.sleep(2)
        raise AssertionError("httpx.get should not be called when cache is warm")

    monkeypatch.setattr("backend.app.services.system_service.httpx.get", slow_get)

    started = _time.perf_counter()
    response = client.get("/pipeline/ready")
    elapsed_ms = (_time.perf_counter() - started) * 1000

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert elapsed_ms < 100, f"readiness probe took {elapsed_ms:.1f}ms, expected <100ms"


def test_live_reports_process_alive(client):
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_corrupt_raw_payload_logs_decode_error(client, monkeypatch):
    """Phase 3: a corrupt raw_payload_json must emit a debug log instead of
    being silently swallowed."""
    from backend.app.db import models as models_module

    captured = []

    class _RecordingLogger:
        def debug(self, msg, *args, **kwargs):
            captured.append((msg % args if args else msg, kwargs))

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

        def info(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(models_module, "logger", _RecordingLogger())

    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        from backend.app.db.models import AuditEvent

        bad = AuditEvent(
            event_fingerprint="corrupt-payload-fixture",
            timestamp=datetime.now(timezone.utc),
            result="Success",
            actor="tester",
            action="kafka.Authentication",
            normalized_action="Authentication",
            action_category="Other",
            resource_type="cluster",
            resource_name="-",
            resource_display="Unknown",
            summary="",
            raw_payload_json="not-a-json",
        )
        db.add(bad)
        db.commit()
        db.refresh(bad)

        # Trigger both enrichment paths.
        _ = bad.source_display
        _ = bad.resource_display_name
    finally:
        session_gen.close()

    decode_messages = [msg for msg, _ in captured if "raw_payload_json" in msg or "failed to decode" in msg]
    assert decode_messages, f"expected a decode-failure debug log, got {captured}"
    assert any(kwargs.get("exc_info") for _, kwargs in captured), "expected exc_info=True on the debug log"


def test_rate_limit_triggers_on_events_and_exempts_live(client):
    """/events list is capped at 20/minute per IP; /live must never be limited."""
    from backend.app.core.limiter import limiter

    limiter.reset()
    limiter.enabled = True
    try:
        # Burn through the per-IP /events budget.
        statuses = []
        for _ in range(25):
            statuses.append(client.get("/events", params={"limit": 1}).status_code)

        # Within the first 20 we should see only 200s; after 20 we should get 429s.
        ok = sum(1 for status in statuses if status == 200)
        too_many = sum(1 for status in statuses if status == 429)
        assert ok <= 20, f"unexpected 200 count {ok} (statuses={statuses})"
        assert too_many >= 1, f"expected at least one 429, got statuses={statuses}"

        # /live is exempt — even after exhausting the events bucket it returns 200.
        for _ in range(5):
            assert client.get("/live").status_code == 200
    finally:
        limiter.enabled = False
        limiter.reset()


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


def test_retention_cleanup_removes_triage_rows(client):
    """Retention cleanup must not leave orphan rows in audit_event_triage."""
    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        from backend.app.services.triage_service import upsert_triage

        old_event = create_event(
            db,
            {
                "id": "old-with-triage",
                "timestamp": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "actor": "retention-triage",
                "methodName": "io.confluent.kafka.server/CreateTopics",
                "resourceName": "crn://confluent.cloud/topic=old-with-triage",
            },
        )
        # Capture the fingerprint up front because the ORM instance becomes
        # detached/expired after the cleanup deletes the row.
        old_fingerprint = old_event.event_fingerprint
        upsert_triage(db, old_fingerprint, "approved", actor="tester", note="approved-old")

        triage_count_before = db.query(AuditEventTriage).filter(
            AuditEventTriage.event_fingerprint == old_fingerprint
        ).count()
        assert triage_count_before == 1

        result = cleanup_retention(db, retention_days=1, dry_run=False)
        assert result["deleted_count"] >= 1

        # Both the event and its triage row must be gone.
        from backend.app.db.models import AuditEvent

        remaining_events = db.query(AuditEvent).filter(
            AuditEvent.event_fingerprint == old_fingerprint
        ).count()
        remaining_triage = db.query(AuditEventTriage).filter(
            AuditEventTriage.event_fingerprint == old_fingerprint
        ).count()
        assert remaining_events == 0
        assert remaining_triage == 0, "audit_event_triage row was orphaned by retention cleanup"
    finally:
        session_gen.close()


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


def test_patterns_enriched_actor_display_name(client):
    from backend.app.db.models import AuditEvent, AuditEventPattern

    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        def _base_event(fingerprint: str) -> AuditEvent:
            return AuditEvent(
                event_fingerprint=fingerprint,
                timestamp=datetime.now(timezone.utc),
                result="Success",
                actor="u-enrichtest",
                action="kafka.Authentication",
                normalized_action="Authentication",
                action_category="Other",
                resource_type="cluster",
                resource_name="-",
                resource_display="Unknown",
                summary="",
            )

        # Good row — real display name (highest id wins)
        good = _base_event("pattern-enrich-good")
        good.actor_display_name = "Enrich Test User"
        good._actor_type = "user"

        # Bad row — raw actor ID stored as display name
        bad_raw = _base_event("pattern-enrich-bad-rawid")
        bad_raw.actor_display_name = "u-enrichtest"
        bad_raw._actor_type = "user"

        # Bad row — empty display name
        bad_empty = _base_event("pattern-enrich-bad-empty")
        bad_empty.actor_display_name = ""
        bad_empty._actor_type = "user"

        db.add_all([bad_raw, bad_empty, good])  # good inserted last = highest id

        pattern = AuditEventPattern(
            pattern_key="u-enrichtest||kafka.Authentication||-",
            actor="u-enrichtest",
            action="kafka.Authentication",
            resource_name="-",
            occurrence_count=25,
            window_count=3,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            status="active",
        )
        db.add(pattern)
        db.commit()
    finally:
        session_gen.close()

    response = client.get("/patterns", params={"status": "active"})
    assert response.status_code == 200
    data = response.json()
    enriched = next((p for p in data["patterns"] if p["actor"] == "u-enrichtest"), None)
    assert enriched is not None, "pattern for u-enrichtest not found in response"
    assert enriched["actor_display_name"] == "Enrich Test User", (
        f"expected real name, got {enriched['actor_display_name']!r}"
    )
    assert enriched["actor_type"] == "user"


def test_stale_patterns_auto_expire(client):
    from backend.app.db.models import AuditEventPattern

    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        stale = AuditEventPattern(
            pattern_key="stale-pattern-expiry-test",
            actor="u-staletest",
            action="kafka.Authentication",
            resource_name="-",
            occurrence_count=11,
            window_count=1,
            first_seen_at=datetime.now(timezone.utc) - timedelta(hours=30),
            last_seen_at=datetime.now(timezone.utc) - timedelta(hours=25),
            status="active",
        )
        db.add(stale)
        db.commit()
    finally:
        session_gen.close()

    # Calling list_patterns should trigger lazy expiry of the stale pattern.
    response = client.get("/patterns", params={"status": "active"})
    assert response.status_code == 200
    data = response.json()
    active_actors = [p["actor"] for p in data["patterns"]]
    assert "u-staletest" not in active_actors, "stale pattern should have been expired"

    # Verify the DB row was updated to 'expired', not deleted.
    session_gen2 = db_override()
    db2 = next(session_gen2)
    try:
        from sqlalchemy import select as sa_select
        row = db2.scalar(
            sa_select(AuditEventPattern).where(
                AuditEventPattern.actor == "u-staletest"
            )
        )
        assert row is not None, "pattern row should still exist (not deleted)"
        assert row.status == "expired", f"expected 'expired', got {row.status!r}"
    finally:
        session_gen2.close()


def test_system_status_requires_viewer_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "viewer-token", "actor_id": "viewer", "role": "viewer"},
        ]),
    )
    no_creds = client.get("/system/status")
    assert no_creds.status_code in {401, 403}


def test_system_status_allowed_when_auth_disabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    response = client.get("/system/status")
    assert response.status_code == 200


def test_system_forwarder_health_requires_viewer_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "viewer-token", "actor_id": "viewer", "role": "viewer"},
        ]),
    )
    no_creds = client.get("/system/forwarder-health")
    assert no_creds.status_code in {401, 403}


def test_system_forwarder_health_allowed_when_auth_disabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    response = client.get("/system/forwarder-health")
    assert response.status_code == 200


def test_system_vacuum_requires_admin_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "viewer-token", "actor_id": "viewer", "role": "viewer"},
            {"token": "admin-token", "actor_id": "admin", "role": "admin"},
        ]),
    )
    no_creds = client.post("/system/vacuum")
    viewer = client.post("/system/vacuum", headers={"Authorization": "Bearer viewer-token"})
    assert no_creds.status_code in {401, 403}
    assert viewer.status_code == 403


def test_system_vacuum_allowed_when_auth_disabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    # vacuum may fail for other reasons (forwarder unreachable) but must not return 401/403
    response = client.post("/system/vacuum")
    assert response.status_code not in {401, 403}


def test_summary_methods_requires_viewer_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "API_AUTH_TOKENS_JSON",
        json.dumps([
            {"token": "viewer-token", "actor_id": "viewer", "role": "viewer"},
        ]),
    )
    no_creds = client.get("/summary/methods")
    assert no_creds.status_code in {401, 403}


def test_summary_methods_allowed_when_auth_disabled(client, monkeypatch):
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    response = client.get("/summary/methods")
    assert response.status_code == 200


def test_summary_flow_groups_subject_display_name(client):
    """flow_groups items include subject_display_name when actor has an enriched name."""
    from backend.app.db.models import AuditEvent as AuditEventModel
    from backend.app.services.event_service import create_event

    db_override = next(iter(client.app.dependency_overrides.values()))
    session_gen = db_override()
    db = next(session_gen)
    try:
        # Insert a batch of events attributed to a test actor with a known display name.
        for i in range(3):
            ev = AuditEventModel(
                event_fingerprint=f"flowgroup-dn-test-{i}",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=i),
                result="Success",
                actor="u-flowdntest",
                action="iam.DeleteRoleBinding",
                normalized_action="DeleteRoleBinding",
                action_category="Delete",
                resource_type="role_binding",
                resource_name="rb-test",
                resource_display="Role Binding: rb-test",
                summary=f"u-flowdntest deleted role binding",
            )
            ev.actor_display_name = "Flow Test Person"
            ev._actor_type = "user"
            db.add(ev)
        db.commit()
    finally:
        session_gen.close()

    response = client.get("/summary", params={"time_window": "1h"})
    assert response.status_code == 200
    data = response.json()
    flow_groups = data.get("flow_groups", [])
    dn_group = next((g for g in flow_groups if g.get("subject") == "u-flowdntest"), None)
    assert dn_group is not None, "flow group for u-flowdntest not found in /summary"
    assert dn_group["subject_display_name"] == "Flow Test Person"
    assert "Flow Test Person" in dn_group["group_title"]
    assert "u-flowdntest" not in dn_group["group_title"]


def test_export_csv_returns_csv_content_type(client):
    response = client.get("/events/export?format=csv&limit=5")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]


def test_export_json_returns_list(client):
    response = client.get("/events/export?format=json&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_retention_cleanup_archives_before_delete(client, monkeypatch):
    """When cold storage is configured, archive is called before delete runs."""
    import backend.app.api.routes.admin as admin_mod

    archive_calls = []
    cleanup_calls = []

    def fake_archive(db, cutoff, prefix="auditlens", dry_run=False):
        archive_calls.append(cutoff)
        return {"enabled": True, "days_archived": 2, "bytes_archived": 4096, "errors": [], "dry_run": dry_run}

    def fake_cleanup(db, days, *, dry_run=False, raw_payload_retention_days=None, noise_retention_days=None):
        cleanup_calls.append(days)
        return {"dry_run": dry_run, "deleted_count": 0, "raw_payloads_nulled": 0, "noise_deleted": 0}

    monkeypatch.setattr(admin_mod, "archive_events_before", fake_archive)
    monkeypatch.setattr(admin_mod, "cleanup_retention", fake_cleanup)
    monkeypatch.setenv("API_AUTH_ENABLED", "false")

    response = client.post("/admin/retention/cleanup", params={"dry_run": "true"})
    assert response.status_code == 200
    assert len(archive_calls) == 1, "archive_events_before should be called once"
    assert len(cleanup_calls) == 1, "cleanup_retention should be called once"
    # Archive called with a cutoff datetime, cleanup called after
    assert hasattr(archive_calls[0], "year"), "archive cutoff must be a datetime"
