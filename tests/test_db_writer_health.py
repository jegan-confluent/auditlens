"""Tests for the /health db_writer block + replay_recommended signal.

Phase 2 Fix 1: detect-and-surface only — these tests lock down the
classification rules so a future refactor can't silently regress the
operator-facing freshness signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import audit_forwarder as fwd


# ──────────────────────── _max_event_timestamp_iso ─────────────────────


def test_max_event_timestamp_returns_latest_in_batch():
    payloads = [
        {"time": "2026-05-09T10:00:00.000Z"},
        {"time": "2026-05-09T10:05:00.000Z"},  # latest
        {"time": "2026-05-09T10:02:30.000Z"},
    ]
    out = fwd._max_event_timestamp_iso(payloads)
    assert out is not None
    assert out.startswith("2026-05-09T10:05:00")
    assert out.endswith("Z")  # UTC-Z suffix; ISO comparison friendly


def test_max_event_timestamp_handles_empty_batch():
    assert fwd._max_event_timestamp_iso([]) is None


def test_max_event_timestamp_skips_unparseable_payloads():
    """One bad payload must not abort the rest of the computation."""
    payloads = [
        {"time": "not a timestamp"},  # fallback to now() — included
        {"time": "2026-05-09T10:00:00.000Z"},
    ]
    out = fwd._max_event_timestamp_iso(payloads)
    # parse_event_timestamp falls back to now() on bad input, so the
    # max is "now" not the literal 2026-05-09 string. We assert non-None
    # and ISO-Z shape, not specific value — the fallback is documented.
    assert out is not None
    assert out.endswith("Z")


def test_max_event_timestamp_normalizes_naive_to_utc():
    payloads = [{"time": "2026-05-09T10:00:00.000"}]  # no tz
    out = fwd._max_event_timestamp_iso(payloads)
    assert out is not None
    assert out.endswith("Z")


# ────────────────────────── _compute_db_behind_seconds ─────────────────


def test_db_behind_seconds_returns_int():
    iso = (datetime.now(timezone.utc) - timedelta(seconds=42)).isoformat().replace("+00:00", "Z")
    assert 40 <= fwd._compute_db_behind_seconds(iso) <= 60


def test_db_behind_seconds_returns_none_for_unknown():
    assert fwd._compute_db_behind_seconds(None) is None
    assert fwd._compute_db_behind_seconds("") is None
    assert fwd._compute_db_behind_seconds("garbage") is None


def test_db_behind_seconds_clamps_negative_to_zero():
    """A clock skew that puts the event in the future must not produce
    a negative behind value — operators can't reason about that."""
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    assert fwd._compute_db_behind_seconds(future) == 0


# ────────────────────────── _classify_db_writer_status ─────────────────


def _now_iso(offset_seconds: int = 0) -> str:
    ts = datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)
    return ts.isoformat().replace("+00:00", "Z")


def test_status_healthy_when_recent_and_no_errors():
    assert fwd._classify_db_writer_status(_now_iso(5), error_count=0) == "healthy"


def test_status_degraded_when_60_to_300_seconds_old():
    assert fwd._classify_db_writer_status(_now_iso(120), error_count=0) == "degraded"


def test_status_degraded_when_recent_but_errors_present():
    assert fwd._classify_db_writer_status(_now_iso(5), error_count=3) == "degraded"


def test_status_stalled_when_older_than_300_seconds():
    assert fwd._classify_db_writer_status(_now_iso(400), error_count=0) == "stalled"


def test_status_stalled_when_last_write_at_is_none():
    """Cold start sits in stalled until first batch lands — matches spec."""
    assert fwd._classify_db_writer_status(None, error_count=0) == "stalled"


def test_status_stalled_overrides_degraded_when_old_and_errors():
    assert fwd._classify_db_writer_status(_now_iso(400), error_count=10) == "stalled"


# ─────────────────────── _is_replay_recommended ────────────────────────


def test_replay_recommended_true_when_kafka_caught_up_db_far_behind():
    assert fwd._is_replay_recommended(consumer_lag=0, db_behind_seconds=600) is True


def test_replay_recommended_false_when_kafka_still_behind():
    """Kafka has events the forwarder hasn't consumed yet — replay
    won't help, the consumer just needs to drain."""
    assert fwd._is_replay_recommended(consumer_lag=10000, db_behind_seconds=600) is False


def test_replay_recommended_false_when_db_only_slightly_behind():
    assert fwd._is_replay_recommended(consumer_lag=0, db_behind_seconds=120) is False


def test_replay_recommended_false_when_inputs_unknown():
    assert fwd._is_replay_recommended(consumer_lag=None, db_behind_seconds=600) is False
    assert fwd._is_replay_recommended(consumer_lag=0, db_behind_seconds=None) is False


def test_replay_recommended_false_at_exactly_300_seconds():
    """Spec is `> 300`, not `>= 300` — boundary case."""
    assert fwd._is_replay_recommended(consumer_lag=0, db_behind_seconds=300) is False
    assert fwd._is_replay_recommended(consumer_lag=0, db_behind_seconds=301) is True


# ────────────────────────── _build_db_writer_block ─────────────────────


def test_build_db_writer_block_shape():
    """The /health response shape is part of the public contract."""
    block = fwd._build_db_writer_block({
        "db_last_successful_write": _now_iso(2),
        "db_last_event_timestamp_iso": _now_iso(8),
        "db_write_consecutive_error_count": 0,
    })
    assert set(block.keys()) == {
        "last_write_at",
        "last_event_timestamp",
        "db_behind_seconds",
        "write_error_count",
        "status",
    }
    assert block["status"] == "healthy"
    assert isinstance(block["db_behind_seconds"], int)


def test_build_db_writer_block_handles_empty_metrics():
    """Cold start: no fields populated yet. Must not raise; must
    return a stalled-shaped block."""
    block = fwd._build_db_writer_block({})
    assert block["last_write_at"] is None
    assert block["last_event_timestamp"] is None
    assert block["db_behind_seconds"] is None
    assert block["write_error_count"] == 0
    assert block["status"] == "stalled"


def test_build_db_writer_block_handles_unparseable_error_count():
    """Defensive: a non-int sneaking into the metrics shape must not raise."""
    block = fwd._build_db_writer_block({
        "db_last_successful_write": _now_iso(5),
        "db_write_consecutive_error_count": "not-an-int",
    })
    # Falls through to the except path → stalled-shaped defaults.
    assert block["status"] == "stalled"
    assert block["write_error_count"] == 0


# ───────────────── Metrics record_db_write_success path ─────────────────


def test_record_db_write_success_advances_event_timestamp_monotonically():
    m = fwd.Metrics()
    m.record_db_write_success(batch_size=10, max_event_timestamp_iso="2026-05-09T10:00:00Z")
    m.record_db_write_success(batch_size=10, max_event_timestamp_iso="2026-05-09T10:05:00Z")
    assert m.db_last_event_timestamp_iso == "2026-05-09T10:05:00Z"
    # Earlier timestamp must NOT regress the watermark.
    m.record_db_write_success(batch_size=10, max_event_timestamp_iso="2026-05-09T09:00:00Z")
    assert m.db_last_event_timestamp_iso == "2026-05-09T10:05:00Z"


def test_record_db_write_success_resets_consecutive_error_count():
    m = fwd.Metrics()
    m.record_db_write_error("boom", batch_size=10)
    m.record_db_write_error("boom", batch_size=10)
    assert m.db_write_consecutive_error_count == 2
    m.record_db_write_success(batch_size=10)
    assert m.db_write_consecutive_error_count == 0


def test_record_db_write_success_with_no_event_timestamp_does_not_clobber():
    """A successful write that happens to have no timestamps in its
    batch (edge case) must not erase the previously-recorded watermark."""
    m = fwd.Metrics()
    m.record_db_write_success(batch_size=10, max_event_timestamp_iso="2026-05-09T10:00:00Z")
    m.record_db_write_success(batch_size=0, max_event_timestamp_iso=None)
    assert m.db_last_event_timestamp_iso == "2026-05-09T10:00:00Z"
