"""FIX 4: Confluent-internal topics are classified as noise.

error-lcc-* topics are auto-created by the Confluent platform (lcc- = cluster ID)
and produced 1036 spurious action_required events.  Other internal prefixes
(_confluent, __consumer_, _schemas) are also suppressed.

Tests verify:
  - kafka.CreateTopics on "error-lcc-abc123" → signal=noise
  - kafka.Produce on "_confluent-metrics" → signal=noise
  - kafka.CreateTopics on "__consumer_offsets" → signal=noise
  - kafka.CreateTopics on "_schemas" → signal=noise
  - kafka.CreateTopics on "user_payments" → NOT suppressed (normal topic)
  - kafka.CreateTopics on "payments-error-lcc-extra" → NOT suppressed (infix, not prefix)
"""
from src.product.event_signals import classify_signal


def _event(action: str, resource_name: str) -> dict:
    return {
        "action": action,
        "methodName": action,
        "resource_name": resource_name,
        "result": "Success",
        "is_denied": False,
        "is_failure": False,
    }


def test_error_lcc_topic_is_noise():
    result = classify_signal(_event("kafka.CreateTopics", "error-lcc-p76qzm"))
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "internal_topic"


def test_error_lcc_produce_is_noise():
    result = classify_signal(_event("kafka.Produce", "error-lcc-59z2zg"))
    assert result["signal_type"] == "noise"


def test_confluent_internal_topic_is_noise():
    result = classify_signal(_event("kafka.CreateTopics", "_confluent-metrics"))
    assert result["signal_type"] == "noise"


def test_consumer_offsets_topic_is_noise():
    result = classify_signal(_event("kafka.CreateTopics", "__consumer_offsets"))
    assert result["signal_type"] == "noise"


def test_schemas_topic_is_noise():
    result = classify_signal(_event("kafka.CreateTopics", "_schemas"))
    assert result["signal_type"] == "noise"


def test_user_topic_not_suppressed():
    """Normal user-created topics must not be affected."""
    result = classify_signal(_event("kafka.CreateTopics", "user_payments"))
    assert result["signal_type"] != "noise"


def test_infix_lcc_not_suppressed():
    """'lcc-' as an infix (not prefix) must not match."""
    result = classify_signal(_event("kafka.CreateTopics", "payments-error-lcc-extra"))
    assert result["signal_type"] != "noise"


def test_error_lcc_delete_is_noise():
    """Deletion of an internal topic is also noise."""
    result = classify_signal(_event("kafka.DeleteTopics", "error-lcc-abc123"))
    assert result["signal_type"] == "noise"
