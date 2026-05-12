"""Foundation contract tests for AuditLens."""

from __future__ import annotations

from unittest.mock import Mock

import orjson
from jsonschema import validate

import audit_forwarder as forwarder

def test_validate_startup_config_reports_missing_required(monkeypatch):
    monkeypatch.setattr(forwarder, "AUDIT_BOOTSTRAP", "")
    monkeypatch.setattr(forwarder, "AUDIT_API_KEY", "")
    monkeypatch.setattr(forwarder, "AUDIT_API_SECRET", "")
    monkeypatch.setattr(forwarder, "DEST_BOOTSTRAP", "")
    monkeypatch.setattr(forwarder, "DEST_API_KEY", "")
    monkeypatch.setattr(forwarder, "DEST_API_SECRET", "")

    summary = forwarder.validate_startup_config()

    assert summary["valid"] is False
    assert "AUDIT_BOOTSTRAP" in summary["missing_required"]["source_audit_cluster"]
    assert "DEST_BOOTSTRAP" in summary["missing_required"]["internal_kafka_topics"]


def test_validate_startup_config_rejects_duplicate_topics(monkeypatch):
    monkeypatch.setattr(forwarder, "AUDIT_BOOTSTRAP", "source:9092")
    monkeypatch.setattr(forwarder, "AUDIT_API_KEY", "key")
    monkeypatch.setattr(forwarder, "AUDIT_API_SECRET", "secret")
    monkeypatch.setattr(forwarder, "DEST_BOOTSTRAP", "dest:9092")
    monkeypatch.setattr(forwarder, "DEST_API_KEY", "key")
    monkeypatch.setattr(forwarder, "DEST_API_SECRET", "secret")
    monkeypatch.setattr(forwarder, "AUDIT_RAW_TOPIC", "audit.raw.v1")
    monkeypatch.setattr(forwarder, "AUDIT_NORMALIZED_TOPIC", "audit.raw.v1")

    summary = forwarder.validate_startup_config()

    assert summary["valid"] is False
    assert "audit.raw.v1" in summary["duplicate_topics"]


def test_normalized_and_enriched_contracts_match_schema(sample_security_event):
    event = sample_security_event
    flat = forwarder.flatten_audit(event)
    normalized = forwarder.build_normalized_event(flat)
    enriched = forwarder.build_enriched_event(flat)
    raw = forwarder.build_raw_event(event, Mock(topic=lambda: "audit-source", partition=lambda: 1, offset=lambda: 5))

    raw_schema = orjson.loads(open("schemas/audit.raw.v1.json", "rb").read())
    normalized_schema = orjson.loads(open("schemas/audit.normalized.v1.json", "rb").read())
    enriched_schema = orjson.loads(open("schemas/audit.enriched.v1.json", "rb").read())

    validate(raw, raw_schema)
    validate(normalized, normalized_schema)
    validate(enriched, enriched_schema)


def test_health_api_returns_rfc3339_timestamps(monkeypatch):
    monkeypatch.setattr(forwarder, "AUDIT_BOOTSTRAP", "source:9092")
    monkeypatch.setattr(forwarder, "AUDIT_API_KEY", "key")
    monkeypatch.setattr(forwarder, "AUDIT_API_SECRET", "secret")
    monkeypatch.setattr(forwarder, "DEST_BOOTSTRAP", "dest:9092")
    monkeypatch.setattr(forwarder, "DEST_API_KEY", "key")
    monkeypatch.setattr(forwarder, "DEST_API_SECRET", "secret")
    monkeypatch.setattr(forwarder.metrics, "get_metrics", lambda: {
        "uptime_seconds": 12,
        "processed_messages_total": 5,
        "processing_rate_per_second": 1.2,
        "error_count": 0,
        "idle_seconds": 5,
        "consumer_lag_total": 3,
        "consumer_lag_by_partition": {"0": 3},
    })

    status_code, payload = forwarder.MetricsHandler._health_payload(None)

    assert status_code == 200
    assert payload["status"] == "healthy"
    assert payload["timestamp"].endswith("Z")
    for component in payload["components"]:
        assert component["last_check"].endswith("Z")


def test_health_api_reports_idle_connected_consumer_as_healthy(monkeypatch):
    monkeypatch.setattr(forwarder, "AUDIT_BOOTSTRAP", "source:9092")
    monkeypatch.setattr(forwarder, "AUDIT_API_KEY", "key")
    monkeypatch.setattr(forwarder, "AUDIT_API_SECRET", "secret")
    monkeypatch.setattr(forwarder, "DEST_BOOTSTRAP", "dest:9092")
    monkeypatch.setattr(forwarder, "DEST_API_KEY", "key")
    monkeypatch.setattr(forwarder, "DEST_API_SECRET", "secret")
    monkeypatch.setattr(forwarder.metrics, "get_metrics", lambda: {
        "uptime_seconds": 120,
        "processed_messages_total": 0,
        "processing_rate_per_second": 0,
        "error_count": 0,
        "idle_seconds": 120,
        "consumer_lag_total": 0,
        "consumer_lag_by_partition": {},
        "consumer_state": "connected",
        "consecutive_error_count": 0,
    })

    status_code, payload = forwarder.MetricsHandler._health_payload(None)

    assert status_code == 200
    assert payload["status"] == "healthy"
    assert payload["state"] == "idle"
    assert payload["observability"]["consumer_runtime"]["consumer_state"] == "idle"
    consumer = next(component for component in payload["components"] if component["name"] == "consumer")
    assert consumer["status"] == "idle"


def test_normalize_json_keys_handles_non_string_nested_keys():
    payload = {
        1: "integer-key",
        None: {"nested": "none-key"},
        "list": [{("tuple", "key"): "tuple-key"}],
    }

    normalized = forwarder._normalize_json_keys(payload)

    assert normalized["1"] == "integer-key"
    assert normalized["None"] == {"nested": "none-key"}
    assert normalized["list"][0]["('tuple', 'key')"] == "tuple-key"
    orjson.dumps(normalized)


def test_send_json_serializes_non_string_keys_without_crashing():
    class FakeHandler:
        def __init__(self):
            self.headers = []
            self.status_code = None
            self.wfile = Mock()

        def send_response(self, status_code):
            self.status_code = status_code

        def send_header(self, key, value):
            self.headers.append((key, value))

        def end_headers(self):
            pass

    handler = FakeHandler()

    forwarder.MetricsHandler._send_json(handler, 200, {1: "ok", "nested": [{None: "value"}]})

    body = handler.wfile.write.call_args.args[0]
    payload = orjson.loads(body)
    assert handler.status_code == 200
    assert payload == {"1": "ok", "nested": [{"None": "value"}]}


def test_send_json_falls_back_without_dumping_payload(monkeypatch, caplog):
    class FakeHandler:
        def __init__(self):
            self.writes = []
            self.wfile = Mock()
            self.wfile.write.side_effect = self.writes.append

        def send_response(self, status_code):
            pass

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    handler = FakeHandler()
    secret_payload = {"token": "do-not-log"}
    original_dumps = forwarder.orjson.dumps

    def fake_dumps(payload, option=None):
        if isinstance(payload, dict) and payload.get("token") == "do-not-log":
            raise TypeError("forced serialization failure")
        return original_dumps(payload, option=option)

    monkeypatch.setattr(forwarder.orjson, "dumps", fake_dumps)

    forwarder.MetricsHandler._send_json(handler, 200, secret_payload)

    # Behavioral assertion change: new fallback is {"status": "ok", "error":
    # "serialization_failed"} and the log is WARNING-level, not ERROR. The
    # critical invariant — secret payload never appears in logs — is unchanged.
    fallback = orjson.loads(handler.writes[-1])
    assert fallback == {"status": "ok", "error": "serialization_failed"}
    assert "Health payload serialization failed" in caplog.text
    assert "do-not-log" not in caplog.text


def test_search_api_returns_recent_enriched_events(monkeypatch):
    monkeypatch.setattr(forwarder, "AUDIT_BOOTSTRAP", "source:9092")
    monkeypatch.setattr(forwarder, "AUDIT_API_KEY", "key")
    monkeypatch.setattr(forwarder, "AUDIT_API_SECRET", "secret")
    monkeypatch.setattr(forwarder, "DEST_BOOTSTRAP", "dest:9092")
    monkeypatch.setattr(forwarder, "DEST_API_KEY", "key")
    monkeypatch.setattr(forwarder, "DEST_API_SECRET", "secret")
    monkeypatch.setattr(forwarder.metrics, "get_metrics", lambda: {
        "uptime_seconds": 12,
        "processed_messages_total": 5,
        "processing_rate_per_second": 1.2,
        "error_count": 0,
        "idle_seconds": 5,
        "consumer_lag_total": 3,
        "consumer_lag_by_partition": {"0": 3},
    })

    forwarder.api_state.enriched_events.clear()
    forwarder.api_state.high_risk_events.clear()
    forwarder.api_state.denial_summaries.clear()
    forwarder.api_state.alerts.clear()
    forwarder.api_state.record_enriched_event({
        "id": "evt-1",
        "time": "2026-04-18T12:00:00Z",
        "principal": "User:sa-123",
        "principal_normalized": "sa-123",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-1",
        "criticality": "CRITICAL",
        "is_high_risk": True,
    })

    params = {"principal": ["sa-123"], "limit": ["10"]}
    snapshot = forwarder.api_state.snapshot()
    matches = [
        event for event in snapshot["enriched_events"]
        if forwarder.MetricsHandler._match_event(None, event, params)
    ]
    payload = {"items": matches, "count": len(matches)}

    assert payload["count"] >= 1
    assert payload["items"][0]["principal_normalized"] == "sa-123"
