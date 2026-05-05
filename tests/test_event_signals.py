from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.services.event_service import create_event
from backend.app.services.summary_service import get_summary
from src.product.event_signals import classify_signal


def signal(payload: dict) -> dict[str, str]:
    return classify_signal(payload)


def test_successful_authentication_is_noise():
    result = signal({"type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"})
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "auth_noise"


def test_successful_authorization_is_noise():
    result = signal({"type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": True})
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "authorization_check"


def test_denied_authorization_is_action_required():
    result = signal({"type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": False})
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "denied_access"


def test_failed_authentication_is_action_required():
    result = signal({"type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "FAILURE"})
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "failure_detected"


def test_failed_read_only_404_uses_review_copy():
    result = signal({"type": "io.confluent.flink.server/request", "methodName": "GetStatement", "resultStatus": "404 NOT_FOUND"})
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "failure_detected"
    assert result["recommended_action"] == "Review failed read request"


def test_read_only_lookup_is_informational():
    for method in ("ListWorkspaces", "GetKafkaClusters", "DescribeCluster"):
        result = signal({"type": "io.confluent.cloud/request", "methodName": method, "resultStatus": "SUCCESS"})
        assert result["signal_type"] == "informational"
        assert result["signal_reason"] == "read_only_lookup"


def test_create_topic_needs_attention_and_delete_topic_requires_action():
    create_result = signal({"type": "io.confluent.kafka.server/request", "methodName": "kafka.CreateTopics", "resourceName": "topic=orders"})
    delete_result = signal({"type": "io.confluent.kafka.server/request", "methodName": "kafka.DeleteTopics", "resourceName": "topic=orders"})
    assert create_result["signal_type"] == "attention"
    assert delete_result["signal_type"] == "action_required"
    assert delete_result["signal_reason"] == "destructive_change"


def test_config_and_access_changes_need_attention():
    config_result = signal({"type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"})
    api_key_result = signal({"type": "io.confluent.cloud/request", "methodName": "CreateAPIKey", "resourceName": "api-key=abc"})
    grant_result = signal({"type": "io.confluent.cloud/request", "methodName": "GrantRole", "resourceName": "rolebinding=abc"})
    assert config_result["signal_type"] == "attention"
    assert config_result["signal_reason"] == "config_changed"
    assert api_key_result["signal_type"] == "attention"
    assert grant_result["signal_type"] == "attention"


def test_unknown_event_has_safe_informational_fallback():
    result = signal({"methodName": "SomethingUnexpected"})
    assert result["signal_type"] == "informational"
    assert result["signal_reason"] == "unknown"


def _summary_for(payloads: list[dict]) -> dict:
    with TemporaryDirectory() as tmp:
        engine = build_engine(f"sqlite:///{Path(tmp) / 'auditlens.db'}")
        init_db(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with SessionLocal() as db:
            for payload in payloads:
                create_event(db, payload)
            return get_summary(db)


def test_summary_all_noise_is_all_clear():
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            {"id": "authz-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": True},
        ]
    )
    assert summary["overall_status"] == "all_clear"
    assert summary["noise_count"] == 2


def test_summary_hide_noise_excludes_routine_noise_from_decision():
    with TemporaryDirectory() as tmp:
        engine = build_engine(f"sqlite:///{Path(tmp) / 'auditlens.db'}")
        init_db(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with SessionLocal() as db:
            create_event(
                db,
                {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            )
            create_event(
                db,
                {"id": "config-1", "type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"},
            )
            summary = get_summary(db, hide_noise=True)

    assert summary["total_events"] == 1
    assert summary["noise_count"] == 0
    assert summary["attention_count"] == 1
    assert summary["overall_status"] == "review_needed"
    assert summary["top_actions"][0]["value"] == "Connector configuration updated"


def test_summary_config_changes_need_review():
    summary = _summary_for(
        [
            {"id": "config-1", "type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"},
        ]
    )
    assert summary["overall_status"] == "review_needed"
    assert summary["attention_count"] == 1


def test_summary_destructive_failures_need_action():
    summary = _summary_for(
        [
            {"id": "delete-1", "type": "io.confluent.kafka.server/request", "methodName": "kafka.DeleteTopics", "resourceName": "topic=orders"},
            {"id": "deny-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": False},
        ]
    )
    assert summary["overall_status"] == "action_required"
    assert summary["action_required_count"] == 2
    assert summary["destructive_count"] == 1


def test_summary_sample_metadata_when_total_exceeds_scan_limit(monkeypatch):
    monkeypatch.setattr("backend.app.services.summary_service.SUMMARY_SCAN_LIMIT", 1)
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            {"id": "auth-2", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
        ]
    )
    assert summary["summary_scope"] == "sampled"
    assert summary["scanned_events"] == 1
    assert summary["sample_limit"] == 1
    assert "latest 1 of 2" in summary["sample_warning"]


def test_flow_groups_prioritize_action_required_before_noise():
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "principal": "u-1", "resultStatus": "SUCCESS"},
            {"id": "deny-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "principal": "u-2", "granted": False},
        ]
    )
    assert summary["flow_groups"][0]["signal_type"] == "action_required"
    assert summary["flow_groups"][0]["decision_label"] == "Action Needed"
