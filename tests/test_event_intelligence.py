from types import SimpleNamespace

import logging

from src.product import actor_enrichment
from src.product.actor_enrichment import _identity_map, clear_actor_enrichment_cache, enrich_actor
from src.product.event_intelligence import classify_event, event_digest
from src.product.event_normalization import normalize_event
from src.product.source_enrichment import extract_source_info


def test_create_topic_classification_and_digest():
    payload = {
        "type": "io.confluent.kafka.server/request",
        "methodName": "kafka.CreateTopics",
        "principal": "sa-prod",
        "resourceName": "crn://confluent.cloud/organization=o/environment=env-1/cloud-cluster=lkc-1/topic=orders",
        "clientIp": "10.2.16.156",
        "cluster_id": "lkc-1",
        "resultStatus": "SUCCESS",
    }

    digest = event_digest(payload)

    assert digest["impact_type"] == "constructive"
    assert digest["change_type"] == "created"
    assert digest["resource_family"] == "topic"
    assert digest["resource_display_short"] == "orders"
    assert digest["subject"] == "sa-prod"
    assert digest["subject_type"] == "service_account"
    assert "crn://" not in digest["event_summary"]


def flink_statement_payload(result="FAILURE"):
    return {
        "id": f"flink-get-statement-{result}",
        "type": "io.confluent.flink.server/request",
        "methodName": "GetStatement",
        "principal": "u-0jwz56",
        "resultStatus": result,
        "requestMetadata": {"clientAddress": [{"ip": "165.1.202.190"}]},
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
    }


def test_flink_statement_primary_resource_and_source_context():
    payload = flink_statement_payload()
    normalized = normalize_event(payload)
    digest = event_digest(payload)
    source = extract_source_info(payload)

    assert normalized["resource_type"] == "statement"
    assert normalized["resource_name"] == "c360-loyalty-revenue-job"
    assert normalized["environment_id"] == "env-mkr6ww"
    assert normalized["flink_region"] == "aws.us-east-1"
    assert normalized["source_ip"] == "165.1.202.190"
    assert normalized["source_context"] == "env-mkr6ww"
    assert normalized["resource_display_name"] == "Statement: c360-loyalty-revenue-job"
    assert normalized["resource_scope"].startswith("environment:env-mkr6ww")
    assert normalized["resource_criticality"] == "medium"
    assert source["source_context"] == "env-mkr6ww"
    assert digest["resource_family"] == "flink"
    assert digest["resource_display_short"] == "c360-loyalty-revenue-job"
    assert digest["change_type"] == "read/listed"
    assert digest["impact_type"] == "read_only"
    assert digest["event_title"] == "Flink statement read failed"
    assert digest["decision_reason"] == "Failed read request. Review if expected or caused by stale/missing resource."


def test_flink_statement_method_classification():
    assert event_digest({"methodName": "GetStatement", "cloudResources": flink_statement_payload()["cloudResources"]})["change_type"] == "read/listed"
    assert event_digest({"methodName": "ListStatements", "cloudResources": flink_statement_payload()["cloudResources"]})["impact_type"] == "read_only"
    assert event_digest({"methodName": "CreateStatement", "cloudResources": flink_statement_payload()["cloudResources"]})["impact_type"] == "constructive"
    assert event_digest({"methodName": "DeleteStatement", "cloudResources": flink_statement_payload()["cloudResources"]})["impact_type"] == "destructive"
    assert event_digest({"methodName": "UpdateStatement", "cloudResources": flink_statement_payload()["cloudResources"]})["impact_type"] == "configuration_change"


def test_delete_topic_is_destructive_high_risk():
    payload = {
        "type": "io.confluent.kafka.server/request",
        "methodName": "kafka.DeleteTopics",
        "principal": "User:123",
        "resourceName": "crn://confluent.cloud/organization=o/environment=env-1/cloud-cluster=lkc-1/topic=payments",
        "resultStatus": "SUCCESS",
    }

    classification = classify_event(payload)

    assert classification["impact_type"] == "destructive"
    assert classification["risk_level"] == "high"
    assert classification["change_type"] == "deleted"


def test_update_config_is_configuration_change():
    payload = {
        "type": "io.confluent.cloud/request",
        "methodName": "UpdateConnectorConfig",
        "principal": "user@example.com",
        "resourceName": "connector=orders-sink",
        "resultStatus": "SUCCESS",
    }

    digest = event_digest(payload)

    assert digest["impact_type"] == "configuration_change"
    assert digest["change_type"] == "updated"
    assert digest["resource_family"] == "connector"
    assert digest["event_title"] == "Connector configuration updated"


def test_list_get_describe_are_read_only():
    for method in ("ListWorkspaces", "GetKafkaClusters", "DescribeCluster"):
        payload = {"type": "io.confluent.cloud/request", "methodName": method, "principal": "u-1"}
        classification = classify_event(payload)
        assert classification["impact_type"] == "read_only"
        assert classification["change_type"] == "read/listed"
        assert classification["risk_level"] == "informational"


def test_authorize_is_check_not_mutation():
    payload = {
        "type": "io.confluent.kafka.server/authorization",
        "methodName": "kafka.Authorize",
        "operation": "Produce",
        "principal": "User:2020737",
        "authzResourceName": "topic=payments",
        "granted": True,
    }

    digest = event_digest(payload)

    assert digest["impact_type"] == "authorization_check"
    assert digest["change_type"] == "authorized"
    assert digest["risk_level"] == "informational"
    assert digest["event_title"] == "Authorization check"


def test_denied_authorization_is_security_sensitive():
    payload = {
        "type": "io.confluent.kafka.server/authorization",
        "methodName": "kafka.Authorize",
        "operation": "Produce",
        "principal": "User:2020737",
        "authzResourceName": "topic=payments",
        "clientIp": "10.2.16.156",
        "granted": False,
    }

    digest = event_digest(payload)

    assert digest["impact_type"] == "security_sensitive"
    assert digest["risk_level"] == "high"
    assert digest["change_type"] == "denied"
    assert digest["event_title"] == "Authorization denied"
    assert digest["source_ip"] == "10.2.16.156"
    assert digest["source_context"] == "Not provided by audit event"


def test_authentication_extracts_user_and_source_ip():
    payload = {
        "type": "io.confluent.kafka.server/authentication",
        "methodName": "kafka.Authentication",
        "principal": "User:2020737",
        "clientIp": "203.0.113.10",
        "resultStatus": "SUCCESS",
    }

    digest = event_digest(payload)

    assert digest["impact_type"] == "authentication"
    assert digest["change_type"] == "authenticated"
    assert digest["subject"] == "User:2020737"
    assert digest["subject_type"] == "user"
    assert digest["source_ip"] == "203.0.113.10"
    assert digest["source_context"] == "Not provided by audit event"


def test_actor_enrichment_uses_mapping_when_available(monkeypatch):
    monkeypatch.setenv(
        "ACTOR_IDENTITY_MAP_JSON",
        '{"u-75rw9o":{"display_name":"Jegan Admin","email":"jegan@example.com","type":"user"}}',
    )
    _identity_map.cache_clear()
    clear_actor_enrichment_cache()
    result = enrich_actor("u-75rw9o")
    assert result["actor_display_name"] == "Jegan Admin"
    assert result["actor_email"] == "jegan@example.com"
    assert result["actor_type"] == "user"
    assert result["actor_raw_id"] == "u-75rw9o"
    assert result["actor_source"] == "manual"
    assert result["actor_confidence"] == "high"


def test_actor_enrichment_manual_mapping_service_account(monkeypatch):
    monkeypatch.setenv(
        "ACTOR_IDENTITY_MAP_JSON",
        '{"sa-domx5qd":{"display_name":"Production Pipeline","email":"pipeline@example.com","type":"service_account"}}',
    )
    _identity_map.cache_clear()
    clear_actor_enrichment_cache()
    result = enrich_actor("sa-domx5qd")
    assert result["actor_display_name"] == "Production Pipeline"
    assert result["actor_email"] == "pipeline@example.com"
    assert result["actor_type"] == "service_account"
    assert result["actor_raw_id"] == "sa-domx5qd"
    assert result["actor_source"] == "manual"
    assert result["actor_confidence"] == "high"


def test_actor_enrichment_audit_event_and_raw_fallbacks(monkeypatch):
    monkeypatch.delenv("ACTOR_IDENTITY_MAP_JSON", raising=False)
    monkeypatch.setenv("IAM_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("METRICS_ENRICHMENT_ENABLED", "false")
    clear_actor_enrichment_cache()
    display = enrich_actor("Jane Admin")
    user = enrich_actor("u-unknown")
    service_account = enrich_actor("sa-domx5qd")
    empty = enrich_actor("")
    assert display["actor_display_name"] == "Jane Admin"
    assert display["actor_source"] == "audit_event"
    assert display["actor_confidence"] == "medium"
    assert user["actor_display_name"] == "u-unknown"
    assert user["actor_raw_id"] == "u-unknown"
    assert user["actor_source"] == "fallback"
    assert service_account["actor_display_name"] == "sa-domx5qd"
    assert service_account["actor_raw_id"] == "sa-domx5qd"
    assert service_account["actor_source"] == "fallback"
    assert empty["actor_display_name"] == "Unknown principal"
    assert empty["actor_source"] == "fallback"


def test_actor_enrichment_uses_confluent_iam_provider(monkeypatch):
    class FakeInfo:
        def __init__(self, identity_id, display_name, email=""):
            self.id = identity_id
            self.display_name = display_name
            self.email = email

    class FakeEnricher:
        def resolve(self, principal):
            if principal == "u-iam123":
                return FakeInfo("u-iam123", "Jane Admin", "jane@example.com")
            if principal == "sa-iam123":
                return FakeInfo("sa-iam123", "Payments Pipeline")
            return FakeInfo(principal, principal)

    monkeypatch.setenv("IAM_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("IAM_ENRICHMENT_SOURCE", "confluent_api")
    monkeypatch.setenv("METRICS_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("CONFLUENT_CLOUD_API_KEY", "configured-key")
    monkeypatch.setenv("CONFLUENT_CLOUD_API_SECRET", "configured-secret")
    clear_actor_enrichment_cache()
    monkeypatch.setattr(actor_enrichment, "_confluent_identity_enricher", lambda: FakeEnricher())

    user = enrich_actor("u-iam123")
    service_account = enrich_actor("sa-iam123")

    assert user["actor_display_name"] == "Jane Admin"
    assert user["actor_email"] == "jane@example.com"
    assert user["actor_source"] == "confluent_api"
    assert user["actor_confidence"] == "high"
    assert service_account["actor_display_name"] == "Payments Pipeline"
    assert service_account["actor_source"] == "confluent_api"
    assert service_account["actor_confidence"] == "high"


def test_actor_enrichment_cache_avoids_repeated_extension_lookup(monkeypatch):
    clear_actor_enrichment_cache()
    monkeypatch.setenv("IAM_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("IAM_ENRICHMENT_SOURCE", "confluent_api")
    monkeypatch.setenv("METRICS_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("CONFLUENT_API_KEY", "configured-key")
    monkeypatch.setenv("CONFLUENT_API_SECRET", "configured-secret")
    calls = {"count": 0}

    def fake_lookup(raw, config):
        calls["count"] += 1
        return {
            "actor_id": raw,
            "actor_display_name": "Cached User",
            "actor_type": "user",
            "actor_source": "confluent_api",
            "actor_confidence": "high",
        }

    monkeypatch.setattr(actor_enrichment, "_lookup_confluent_principal", fake_lookup)
    first = enrich_actor("u-cache")
    second = enrich_actor("u-cache")
    assert first["actor_display_name"] == "Cached User"
    assert second["actor_display_name"] == "Cached User"
    assert calls["count"] == 1


def test_actor_enrichment_failure_falls_back_without_logging_secrets(monkeypatch, caplog):
    clear_actor_enrichment_cache()
    monkeypatch.setenv("IAM_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("IAM_ENRICHMENT_SOURCE", "confluent_api")
    monkeypatch.setenv("METRICS_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("CONFLUENT_API_KEY", "sensitive-key")
    monkeypatch.setenv("CONFLUENT_API_SECRET", "sensitive-secret")

    def failing_lookup(raw, config):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(actor_enrichment, "_lookup_confluent_principal", failing_lookup)
    with caplog.at_level(logging.INFO):
        result = enrich_actor("u-fallback")
    assert result["actor_display_name"] == "u-fallback"
    assert result["actor_source"] == "fallback"
    assert "sensitive-key" not in caplog.text
    assert "sensitive-secret" not in caplog.text


def test_metrics_correlation_is_not_high_confidence_by_default(monkeypatch):
    clear_actor_enrichment_cache()
    monkeypatch.setenv("IAM_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("METRICS_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("METRICS_ENRICHMENT_SOURCE", "correlation")
    monkeypatch.setenv("IAM_METRICS_IDENTITY_MAP_JSON", '{"u-metrics123":{"display_name":"Metrics User"}}')
    result = enrich_actor("u-metrics123")
    assert result["actor_display_name"] == "Metrics User"
    assert result["actor_source"] == "metrics"
    assert result["actor_confidence"] in {"low", "medium"}
    assert result["actor_confidence"] != "high"


def test_source_ip_prefers_client_ip_over_cluster_id():
    payload = {
        "clientIp": "134.238.241.34",
        "cluster_id": "lkc-k9382g",
        "methodName": "kafka.DeleteTopics",
    }
    normalized = normalize_event(payload)
    source = extract_source_info(payload)
    assert normalized["source_ip"] == "134.238.241.34"
    assert source["source_display"] == "134.238.241.34"
    assert source["source_display"] != "lkc-k9382g"


def test_source_ip_falls_back_to_nested_request_metadata():
    payload = {
        "data_json": '{"requestMetadata":{"clientAddress":[{"ip":"203.0.113.44"}]}}',
        "cluster_id": "lkc-k9382g",
    }
    source = extract_source_info(payload)
    assert source["source_ip"] == "203.0.113.44"
    assert source["source_display"] == "203.0.113.44"


def test_source_ip_falls_back_to_top_level_request_metadata():
    payload = {
        "requestMetadata": {"clientAddress": [{"ip": "203.0.113.45"}]},
        "cluster_id": "lkc-k9382g",
    }
    source = extract_source_info(payload)
    assert source["source_ip"] == "203.0.113.45"
    assert source["source_display"] == "203.0.113.45"


def test_source_display_does_not_fallback_to_cluster_id():
    payload = {"cluster_id": "lkc-k9382g"}
    source = extract_source_info(payload)
    assert source["source_display"] == "Not provided by audit event"
    assert source["source_display"] != "lkc-k9382g"


def test_decision_reason_is_explainable():
    digest = event_digest({"methodName": "kafka.DeleteTopics", "resourceName": "topic=jegan-testing"})
    assert digest["decision_reason"] == "Destructive operation: topic deletion"


def test_model_digest_uses_existing_columns_and_shortens_resource():
    event = SimpleNamespace(
        actor="sa-prod",
        action="kafka.CreateTopics",
        resource_type="Topic",
        resource_name="orders",
        resource_display="Topic: orders",
        source_ip="10.0.0.1",
        cluster_id="lkc-1",
        is_failure=False,
        is_denied=False,
        summary="sa-prod created topic orders",
    )

    digest = event_digest({}, event)

    assert digest["subject"] == "sa-prod"
    assert digest["subject_type"] == "service_account"
    assert digest["resource_display_short"] == "orders"
    assert digest["source_ip"] == "10.0.0.1"
    assert digest["source_context"] == "lkc-1"
