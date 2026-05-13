"""Tests for principal normalization used by AuditLens foundation."""

import audit_forwarder as forwarder
from src.identity import normalize_principal, classify_principal_type, normalize_with_type


def test_normalize_principal_strips_user_prefix():
    assert normalize_principal("User:sa-abc123") == "sa-abc123"


def test_normalize_principal_preserves_plain_ids():
    assert normalize_principal("u-abc123") == "u-abc123"


def test_classify_service_account():
    assert classify_principal_type("sa-abc123") == "service_account"


def test_classify_user():
    assert classify_principal_type("u-abc123") == "user"


def test_normalize_with_type_unknown():
    assert normalize_with_type("admin@example.com") == ("admin@example.com", "unknown")


def _make_event_with_principal(principal: str, principal_resource_id: str | None = None) -> dict:
    authn = {"principal": principal}
    if principal_resource_id is not None:
        authn["principalResourceId"] = principal_resource_id
    return {"data": {"serviceName": "test", "methodName": "kafka.CreateTopics", "authenticationInfo": authn}}


def test_flatten_audit_uses_principalResourceId_for_numeric_user():
    """User:3958188 + principalResourceId=u-79z161 → normalized to u-79z161."""
    evt = _make_event_with_principal("User:3958188", "u-79z161")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "u-79z161"
    assert flat["principal_type"] == "user"
    assert flat["principal"] == "User:3958188"  # raw is preserved


def test_flatten_audit_no_override_when_no_principalResourceId():
    """Numeric User:NNNN without principalResourceId stays as numeric stripped form."""
    evt = _make_event_with_principal("User:3958188")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "3958188"
    assert flat["principal_type"] == "unknown"


def test_flatten_audit_no_override_for_proper_user_id():
    """User:u-79z161 already has a valid Confluent ID — no principalResourceId override needed."""
    evt = _make_event_with_principal("User:u-79z161")
    flat = forwarder.flatten_audit(evt)
    assert flat["principal_normalized"] == "u-79z161"
    assert flat["principal_type"] == "user"


def test_map_client_tool_rdkafka():
    """rdkafka/ prefix maps to librdkafka client."""
    assert forwarder._map_client_tool("rdkafka/1.9.2") == "librdkafka client (C/C++/Python/Go)"


def test_map_client_tool_proxy():
    """proxy: prefix maps to Confluent Console / VS Code / CLI."""
    assert forwarder._map_client_tool("proxy:1.0.0") == "Confluent Console / VS Code / CLI"


def test_map_client_tool_confluent_python():
    """confluent-kafka- prefix maps to Confluent Python client."""
    assert forwarder._map_client_tool("confluent-kafka-2.0.2") == "Confluent Python client"


def test_map_client_tool_java():
    """Apache Kafka prefix maps to Java Kafka client."""
    assert forwarder._map_client_tool("Apache Kafka 3.4") == "Java Kafka client"


def test_map_client_tool_sarama():
    """sarama/ prefix maps to Go Sarama client."""
    assert forwarder._map_client_tool("sarama/1.38.1") == "Go Sarama client"


def test_map_client_tool_unknown_passthrough():
    """Unknown clientId is returned as-is."""
    assert forwarder._map_client_tool("my-custom-client/1.0") == "my-custom-client/1.0"


def test_map_client_tool_none():
    """None input returns None."""
    assert forwarder._map_client_tool(None) is None


def test_flatten_audit_sets_client_tool():
    """flatten_audit sets client_tool when clientId is present in request."""
    evt = {
        "data": {
            "serviceName": "test",
            "methodName": "kafka.CreateTopics",
            "authenticationInfo": {"principal": "User:u-abc123"},
            "request": {"clientId": "rdkafka/1.9.2"},
        }
    }
    flat = forwarder.flatten_audit(evt)
    assert flat["client_tool"] == "librdkafka client (C/C++/Python/Go)"
    assert flat["clientId"] == "rdkafka/1.9.2"
