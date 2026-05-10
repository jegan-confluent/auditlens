"""Tests for the consumer-thread noise short-circuit machinery.

The short-circuit pulls bulk-noise events out of the per-batch flow at
the consume point, routes them straight to the bulk writer, and uses a
persistence barrier to keep at-least-once intact: the processor must not
commit a partition's offset past a short-circuited noise offset until
the bulk writer has actually INSERTed it.

These tests exercise the module-level helpers in isolation; the consumer
thread integration is covered by docker-compose smoke validation.
"""

from __future__ import annotations

import threading
import time

import audit_forwarder as fwd


# Reset module-level barrier state between tests so order doesn't matter.
def _reset_barrier_state() -> None:
    with fwd._noise_persisted_cv:
        fwd._noise_persisted_offsets.clear()


class _FakeMsg:
    """Minimal stand-in for a confluent_kafka Message with .value()."""

    def __init__(self, value: bytes):
        self._value = value

    def value(self) -> bytes:
        return self._value


# ───────────────────── _try_short_circuit_noise ────────────────────────


def test_short_circuit_recognises_kafka_fetch_noise():
    msg = _FakeMsg(b'{"data":{"methodName":"kafka.Fetch"}}')
    payload = fwd._try_short_circuit_noise(msg)
    assert payload is not None
    assert payload["data"]["methodName"] == "kafka.Fetch"


def test_short_circuit_recognises_mds_authorize_noise():
    msg = _FakeMsg(b'{"data":{"methodName":"mds.Authorize"}}')
    assert fwd._try_short_circuit_noise(msg) is not None


def test_short_circuit_handles_top_level_method_name():
    """flatten_audit-shaped events have methodName at top-level."""
    msg = _FakeMsg(b'{"methodName":"kafka.Produce"}')
    assert fwd._try_short_circuit_noise(msg) is not None


def test_short_circuit_rejects_non_noise_method():
    msg = _FakeMsg(b'{"data":{"methodName":"kafka.DeleteTopics"}}')
    assert fwd._try_short_circuit_noise(msg) is None


def test_short_circuit_rejects_event_without_method():
    msg = _FakeMsg(b'{"data":{"resourceName":"orders"}}')
    assert fwd._try_short_circuit_noise(msg) is None


def test_short_circuit_returns_none_on_invalid_json():
    msg = _FakeMsg(b"this is not json")
    assert fwd._try_short_circuit_noise(msg) is None


def test_short_circuit_returns_none_on_null_value():
    msg = _FakeMsg(b"null")
    assert fwd._try_short_circuit_noise(msg) is None


def test_short_circuit_returns_none_on_empty_bytes():
    msg = _FakeMsg(b"")
    assert fwd._try_short_circuit_noise(msg) is None


def test_short_circuit_does_not_raise_on_value_error():
    """msg.value() raising must never propagate out of the helper."""
    class _Boom:
        def value(self):
            raise RuntimeError("boom")
    assert fwd._try_short_circuit_noise(_Boom()) is None


def test_short_circuit_method_match_is_case_insensitive():
    msg = _FakeMsg(b'{"data":{"methodName":"Kafka.Fetch"}}')
    assert fwd._try_short_circuit_noise(msg) is not None


# ────────────────────── persistence barrier ────────────────────────────


def test_record_noise_persisted_advances_per_partition_high_watermark():
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 5},
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 7},
        {"_short_circuit": True, "_topic": "t1", "_partition": 1, "_offset": 3},
    ])
    assert fwd._noise_persisted_offsets[("t1", 0)] == 7
    assert fwd._noise_persisted_offsets[("t1", 1)] == 3


def test_record_noise_persisted_never_regresses():
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 10},
    ])
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 4},
    ])
    assert fwd._noise_persisted_offsets[("t1", 0)] == 10


def test_record_noise_persisted_skips_items_without_short_circuit_flag():
    """Items routed to bulk_queue from the processor's _route_to_queue
    don't carry _short_circuit metadata. They must be ignored here so
    their offsets ride on batch_max_offsets in the processor."""
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"some": "enriched-event-shape"},  # no _short_circuit
    ])
    assert fwd._noise_persisted_offsets == {}


def test_record_noise_persisted_handles_empty_batch():
    _reset_barrier_state()
    fwd._record_noise_persisted([])
    assert fwd._noise_persisted_offsets == {}


def test_await_noise_persisted_returns_true_when_already_satisfied():
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 100},
    ])
    assert fwd._await_noise_persisted({("t1", 0): 50}, timeout=0.1) is True


def test_await_noise_persisted_returns_true_for_empty_required():
    _reset_barrier_state()
    assert fwd._await_noise_persisted({}, timeout=0.0) is True


def test_await_noise_persisted_times_out_when_offset_lags():
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 10},
    ])
    started = time.monotonic()
    assert fwd._await_noise_persisted({("t1", 0): 50}, timeout=0.5) is False
    elapsed = time.monotonic() - started
    # Must actually wait close to the full timeout — guards against an
    # accidental tight-poll regression that would burn CPU.
    assert elapsed >= 0.4


def test_await_noise_persisted_wakes_when_writer_acks():
    """The barrier must wake within milliseconds of the bulk writer
    advancing the high-watermark, not poll on a fixed schedule."""
    _reset_barrier_state()

    def _ack_after_delay():
        time.sleep(0.1)
        fwd._record_noise_persisted([
            {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 50},
        ])

    threading.Thread(target=_ack_after_delay, daemon=True).start()
    started = time.monotonic()
    ok = fwd._await_noise_persisted({("t1", 0): 50}, timeout=5.0)
    elapsed = time.monotonic() - started
    assert ok is True
    # Should wake quickly after the ack — not wait the full 5s timeout.
    assert elapsed < 1.0


def test_await_noise_persisted_handles_multi_partition_requirement():
    _reset_barrier_state()
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 0, "_offset": 50},
    ])
    # Partition 1 is missing. Must time out.
    assert fwd._await_noise_persisted(
        {("t1", 0): 50, ("t1", 1): 1},
        timeout=0.2,
    ) is False
    fwd._record_noise_persisted([
        {"_short_circuit": True, "_topic": "t1", "_partition": 1, "_offset": 1},
    ])
    # Now both satisfied.
    assert fwd._await_noise_persisted(
        {("t1", 0): 50, ("t1", 1): 1},
        timeout=0.1,
    ) is True
