"""Tests for GET /actors/{actor_id}/narrative endpoint and narrative service."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.services.event_service import create_event
from backend.app.services.narrative_service import get_actor_narrative


def _session():
    tmp = TemporaryDirectory()
    engine = build_engine(f"sqlite:///{Path(tmp.name) / 'narrative_test.db'}")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmp, SessionLocal


def _make_event(db, uid: str, actor: str, category: str = "Create", signal: str = "informational", **kwargs):
    ts = kwargs.pop("timestamp", datetime.now(timezone.utc).isoformat())
    # Use kafka-prefixed method so event_fingerprint uses the unique "id" field
    # (management-plane fingerprint uses actor+action+timestamp, which collides
    # when multiple events share the same actor and are created within the same second)
    ev = create_event(db, {
        "id": f"narrative-{uid}",
        "timestamp": ts,
        "methodName": "kafka.TestEvent",
        "principal": actor,
    })
    ev.action_category = category
    ev._signal_type = signal
    ev.is_routine_noise = signal == "noise"
    for k, v in kwargs.items():
        setattr(ev, k, v)
    db.commit()
    return ev


# ---------------------------------------------------------------------------
# Test 1: endpoint returns 200 with correct shape
# ---------------------------------------------------------------------------

def test_narrative_returns_correct_shape():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "s1", "u-abc123", category="Create", signal="informational")
            _make_event(db, "s2", "u-abc123", category="Delete", signal="attention")

            result = get_actor_narrative(db, "u-abc123", "24h")

        assert result["actor"] == "u-abc123"
        assert result["time_window"] == "24h"
        assert "total_events" in result
        assert "non_noise_count" in result
        assert "headline" in result
        assert "chapters" in result
        assert "anomalies" in result
        assert "generated_at" in result
        assert result["total_events"] == 2
        assert result["non_noise_count"] == 2
        assert "u-abc123" in result["headline"] or result["headline"]
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# Test 2: chapter grouping is correct for mixed event types
# ---------------------------------------------------------------------------

def test_chapter_grouping_by_category():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            _make_event(db, "c1", "u-chaptest", category="Create", signal="informational")
            _make_event(db, "c2", "u-chaptest", category="Create", signal="attention")
            _make_event(db, "c3", "u-chaptest", category="Delete", signal="action_required")
            _make_event(db, "c4", "u-chaptest", category="Other", signal="noise")

            result = get_actor_narrative(db, "u-chaptest", "24h")

        categories = {ch["category"]: ch for ch in result["chapters"]}
        assert "Create" in categories
        assert categories["Create"]["event_count"] == 2
        assert "Delete" in categories
        assert categories["Delete"]["event_count"] == 1
        assert categories["Delete"]["peak_signal"] == "action_required"
        assert "Other" in categories
        assert result["non_noise_count"] == 3
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# Test 3: off-hours anomaly detected
# ---------------------------------------------------------------------------

def test_off_hours_anomaly_detected():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            # Use a timestamp within 24h but at 02:00 UTC (off-hours)
            # Take now and set hour to 2, keeping it within today to stay in the 24h window
            now = datetime.now(timezone.utc)
            ts_offhours = now.replace(hour=2, minute=0, second=0, microsecond=0).isoformat()
            _make_event(db, "oh1", "u-nightowl", timestamp=ts_offhours, signal="informational")

            result = get_actor_narrative(db, "u-nightowl", "24h")

        anomaly_types = [a["type"] for a in result["anomalies"]]
        assert "off_hours" in anomaly_types
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# Test 4: empty actor returns 0 events gracefully
# ---------------------------------------------------------------------------

def test_empty_actor_returns_zero_gracefully():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            result = get_actor_narrative(db, "u-nonexistent", "24h")

        assert result["actor"] == "u-nonexistent"
        assert result["total_events"] == 0
        assert result["non_noise_count"] == 0
        assert result["chapters"] == []
        assert result["anomalies"] == []
        assert "0 meaningful" in result["headline"]
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# Test 5: deletion spike anomaly detected
# ---------------------------------------------------------------------------

def test_deletion_spike_anomaly_detected():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            for i in range(6):
                _make_event(db, f"del{i}", "u-deleter", category="Delete", signal="attention")

            result = get_actor_narrative(db, "u-deleter", "24h")

        anomaly_types = [a["type"] for a in result["anomalies"]]
        assert "deletion_spike" in anomaly_types
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# Test 6: headline uses display name when available
# ---------------------------------------------------------------------------

def test_headline_uses_display_name():
    tmp, SessionLocal = _session()
    try:
        with SessionLocal() as db:
            ev = _make_event(db, "dn1", "sa-svcabc", signal="informational")
            ev._actor_display_name = "Data Pipeline Bot"
            db.commit()

            result = get_actor_narrative(db, "sa-svcabc", "24h")

        assert "Data Pipeline Bot" in result["headline"]
    finally:
        tmp.cleanup()
