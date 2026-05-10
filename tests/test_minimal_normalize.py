"""Tests for minimal_normalize — the noise-table fast path.

minimal_normalize must:
  1. Return *exactly* the columns physically stored in audit_events_noise.
  2. Handle both raw CloudEvents (data.* nested) and post-flatten_audit
     dicts (top-level fields).
  3. Never raise on malformed input — fall back to safe defaults.
"""

from datetime import datetime, timezone

from src.product.event_normalization import (
    NOISE_TABLE_FIELDS,
    minimal_normalize,
)


# Columns physically present on audit_events_noise (excluding the
# DB-managed `id` and server-default `ingested_at`). Locks the contract
# in a single place so this test fails loudly if the table or the
# normalizer drift apart.
EXPECTED_FIELDS = {
    "timestamp",
    "actor",
    "action",
    "result",
    "resource_name",
    "source_ip",
    "environment_id",
    "cluster_id",
    "is_denied",
}


def _raw_kafka_fetch_event() -> dict:
    """A representative raw CloudEvents-shaped kafka.Fetch noise event."""
    return {
        "id": "evt-1",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1/environment=env-aaa/kafka=lkc-bbb",
        "subject": "crn://confluent.cloud/organization=org1/environment=env-aaa/kafka=lkc-bbb",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2026-01-15T10:30:00.000Z",
        "data": {
            "methodName": "kafka.Fetch",
            "authenticationInfo": {
                "principal": {
                    "confluentServiceAccount": {"resourceId": "sa-aaa111"},
                },
            },
            "authorizationInfo": {
                "granted": True,
                "operation": "Read",
                "resourceType": "Topic",
                "resourceName": "orders",
            },
            "result": {"status": "SUCCESS"},
            "clientAddress": [{"ip": "10.0.0.5"}],
        },
    }


def _flat_kafka_fetch_event() -> dict:
    """A representative post-flatten_audit dict for the same event."""
    return {
        "id": "evt-1",
        "methodName": "kafka.Fetch",
        "principal": "sa-aaa111",
        "principal_raw": "sa-aaa111",
        "principal_normalized": "sa-aaa111",
        "principal_type": "service_account",
        "granted": True,
        "operation": "Read",
        "resourceType": "Topic",
        "authzResourceName": "orders",
        "resourceName": "orders",
        "clientIp": "10.0.0.5",
        "environment_id": "env-aaa",
        "cluster_id": "lkc-bbb",
        "time": "2026-01-15T10:30:00.000Z",
        "resultStatus": "SUCCESS",
    }


# ─────────────────────────── shape contract ────────────────────────────


def test_returned_keys_exactly_match_noise_table_columns():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert set(out.keys()) == EXPECTED_FIELDS
    # And the published constant agrees with the runtime shape.
    assert set(NOISE_TABLE_FIELDS) == EXPECTED_FIELDS


def test_no_decision_or_enrichment_columns_present():
    """Decision fields are constants for noise rows (signal_type='noise',
    signal_reason='bulk_noise'); they're hardcoded by the API layer, not
    stored. The normalizer must not return them."""
    out = minimal_normalize(_raw_kafka_fetch_event())
    forbidden = {
        "signal_type",
        "signal_reason",
        "actor_type",
        "actor_id",
        "actor_display_name",
        "actor_email",
        "actor_source",
        "actor_confidence",
        "resource_type",
        "resource_display",
        "summary",
        "event_title",
        "event_summary",
        "impact_type",
        "risk_level",
        "change_type",
        "is_failure",
        "raw_payload_json",
    }
    assert forbidden.isdisjoint(out.keys())


# ──────────────────────── raw CloudEvents shape ────────────────────────


def test_raw_event_extracts_method_name_from_data():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["action"] == "kafka.Fetch"


def test_raw_event_resolves_principal_from_service_account():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["actor"] == "sa-aaa111"


def test_raw_event_extracts_environment_and_cluster_from_crn():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["environment_id"] == "env-aaa"
    assert out["cluster_id"] == "lkc-bbb"


def test_raw_event_extracts_client_ip_from_data():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["source_ip"] == "10.0.0.5"


def test_raw_event_resource_name_from_authorization_info():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["resource_name"] == "orders"


def test_raw_event_timestamp_is_timezone_aware():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert isinstance(out["timestamp"], datetime)
    assert out["timestamp"].tzinfo is not None


# ───────────────────── post-flatten_audit shape ────────────────────────


def test_flat_event_extracts_method_name_from_top_level():
    out = minimal_normalize(_flat_kafka_fetch_event())
    assert out["action"] == "kafka.Fetch"


def test_flat_event_uses_top_level_principal_when_data_absent():
    out = minimal_normalize(_flat_kafka_fetch_event())
    assert out["actor"] == "sa-aaa111"


def test_flat_event_uses_top_level_environment_and_cluster():
    out = minimal_normalize(_flat_kafka_fetch_event())
    assert out["environment_id"] == "env-aaa"
    assert out["cluster_id"] == "lkc-bbb"


def test_flat_event_uses_top_level_client_ip():
    out = minimal_normalize(_flat_kafka_fetch_event())
    assert out["source_ip"] == "10.0.0.5"


# ─────────────────────────── result / denial ───────────────────────────


def test_granted_true_yields_success_result():
    out = minimal_normalize(_raw_kafka_fetch_event())
    assert out["result"] == "Success"
    assert out["is_denied"] is False


def test_granted_false_yields_denied_failure():
    event = _raw_kafka_fetch_event()
    event["data"]["authorizationInfo"]["granted"] = False
    event["data"]["result"] = {"status": "PERMISSION_DENIED"}
    out = minimal_normalize(event)
    assert out["is_denied"] is True
    assert out["result"] == "Failure"


def test_failed_status_string_marks_failure_even_when_granted():
    event = _raw_kafka_fetch_event()
    event["data"]["result"] = {"status": "FAILURE"}
    out = minimal_normalize(event)
    assert out["result"] == "Failure"
    # Not denied — granted is True. Failure must not imply denial.
    assert out["is_denied"] is False


# ──────────────────────────── robustness ───────────────────────────────


def test_completely_empty_event_does_not_raise():
    out = minimal_normalize({})
    assert set(out.keys()) == EXPECTED_FIELDS
    assert out["actor"] == "unknown"
    assert out["action"] == ""
    assert out["result"] == "Success"
    assert out["is_denied"] is False
    assert out["resource_name"] is None
    assert out["source_ip"] is None
    assert isinstance(out["timestamp"], datetime)


def test_non_dict_input_does_not_raise():
    out = minimal_normalize(None)  # type: ignore[arg-type]
    assert set(out.keys()) == EXPECTED_FIELDS
    assert out["actor"] == "unknown"


def test_data_is_string_not_dict_does_not_raise():
    """Some upstream test fixtures stash data as JSON-encoded string;
    minimal_normalize must treat it as absent rather than crashing."""
    event = {"methodName": "kafka.Fetch", "data": "not-a-dict"}
    out = minimal_normalize(event)
    assert out["action"] == "kafka.Fetch"
    assert out["actor"] == "unknown"


def test_principal_as_plain_string_in_auth_info():
    event = _raw_kafka_fetch_event()
    event["data"]["authenticationInfo"]["principal"] = "User:sa-zzz999"
    out = minimal_normalize(event)
    assert out["actor"] == "User:sa-zzz999"


def test_field_truncation_respects_column_widths():
    event = {
        "methodName": "x" * 1000,
        "principal": "y" * 1000,
        "resourceName": "z" * 2000,
        "clientIp": "1.2.3.4." * 100,
        "environment_id": "e" * 1000,
        "cluster_id": "c" * 1000,
        "time": "2026-01-15T10:30:00.000Z",
    }
    out = minimal_normalize(event)
    assert len(out["action"]) <= 255
    assert len(out["actor"]) <= 255
    assert len(out["resource_name"]) <= 512
    assert len(out["source_ip"]) <= 128
    assert len(out["environment_id"]) <= 255
    assert len(out["cluster_id"]) <= 255


def test_missing_time_falls_back_to_now_utc():
    out = minimal_normalize({"methodName": "kafka.Fetch"})
    assert isinstance(out["timestamp"], datetime)
    assert out["timestamp"].tzinfo is not None
    # Must be very recent (within a minute) — sanity check on the fallback.
    delta = abs((datetime.now(timezone.utc) - out["timestamp"]).total_seconds())
    assert delta < 60
