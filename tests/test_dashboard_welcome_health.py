"""Tests for dashboard Welcome tab health payload normalization."""

import sys
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from tabs.welcome import normalize_forwarder_health, storage_warning_summary
import tabs.welcome as welcome


class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.captions: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def markdown(self, *_args, **_kwargs):
        return None

    def metric(self, *_args, **_kwargs):
        return None

    def divider(self):
        return None

    def columns(self, count):
        return [_FakeColumn() for _ in range(count)]

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, value, *_args, **_kwargs):
        self.warnings.append(value)
        return None

    def error(self, value, *_args, **_kwargs):
        self.errors.append(value)
        return None

    def caption(self, value, *_args, **_kwargs):
        self.captions.append(value)

    def text_input(self, *_args, **_kwargs):
        return ""

    def expander(self, *_args, **_kwargs):
        return _FakeColumn()


def test_normalize_forwarder_health_supports_current_top_level_payload():
    result = normalize_forwarder_health(
        {
            "status": "healthy",
            "coverage": {
                "mode": "persistence_plus_recent_cache",
                "note": "Recent search/export uses persistence.",
                "api_window_counts": {"enriched_events": 12, "alerts": 2},
            },
            "freshness": {"last_enriched_ingest_at": "2026-04-23T14:14:47Z"},
            "recovery": {"replay_in_progress": False},
            "offset_recovery": {"model": "consumer_group_only"},
            "observability": {"offset_commits_total": 3},
            "components": [{"name": "persistence", "status": "healthy"}],
            "processed_total": 42,
            "consumer_lag": 7,
        }
    )

    assert result["coverage"]["mode"] == "persistence_plus_recent_cache"
    assert result["coverage"]["api_window_counts"]["enriched_events"] == 12
    assert result["freshness"]["last_enriched_ingest_at"] == "2026-04-23T14:14:47Z"
    assert result["recovery"]["replay_in_progress"] is False
    assert result["offset_recovery"]["model"] == "consumer_group_only"
    assert result["observability"]["offset_commits_total"] == 3
    assert result["components"] == [{"name": "persistence", "status": "healthy"}]
    assert result["processed_total"] == 42
    assert result["consumer_lag"] == 7


def test_normalize_forwarder_health_supports_service_check_details_wrapper():
    result = normalize_forwarder_health(
        {
            "status": "healthy",
            "details": {
                "coverage": {"mode": "persistence_plus_recent_cache"},
                "components": [{"name": "consumer", "status": "healthy"}],
            },
        }
    )

    assert result["coverage"]["mode"] == "persistence_plus_recent_cache"
    assert result["components"] == [{"name": "consumer", "status": "healthy"}]


def test_normalize_forwarder_health_prefers_nested_details_then_payload_then_top_level():
    result = normalize_forwarder_health(
        {
            "coverage": {"note": "top-level"},
            "components": [{"name": "top-level"}],
            "details": {
                "coverage": {"note": "payload"},
                "components": [{"name": "payload"}],
                "details": {
                    "coverage": {"note": "nested"},
                    "components": [{"name": "nested"}],
                },
            },
        }
    )

    assert result["coverage"]["note"] == "nested"
    assert result["components"] == [{"name": "nested"}]


def test_normalize_forwarder_health_falls_back_when_nested_details_are_empty_or_malformed():
    result = normalize_forwarder_health(
        {
            "coverage": {"note": "top-level"},
            "components": [{"name": "top-level"}],
            "details": {
                "coverage": {"note": "payload"},
                "components": [{"name": "payload"}],
                "details": {"coverage": {}, "components": "not-a-list"},
            },
        }
    )

    assert result["coverage"]["note"] == "payload"
    assert result["components"] == [{"name": "payload"}]


def test_normalize_forwarder_health_supports_legacy_nested_details_payload():
    result = normalize_forwarder_health(
        {
            "status": "healthy",
            "details": {
                "details": {
                    "coverage": {"note": "legacy coverage"},
                    "freshness": {"last_committed_at": "2026-04-23T14:00:00Z"},
                }
            },
        }
    )

    assert result["coverage"]["note"] == "legacy coverage"
    assert result["freshness"]["last_committed_at"] == "2026-04-23T14:00:00Z"


def test_normalize_forwarder_health_handles_missing_or_string_details():
    for payload in ({"status": "degraded", "details": "HTTP 503"}, {"status": "healthy", "details": None}, {}):
        result = normalize_forwarder_health(payload)

        assert result["coverage"] == {}
        assert result["freshness"] == {}
        assert result["recovery"] == {}
        assert result["components"] == []
        assert result["raw_payload_available"] is False


def test_welcome_render_uses_normalized_current_health_payload(monkeypatch):
    fake_st = _FakeStreamlit()

    def fake_health(url, timeout=2.0):
        if "api/v1/health" in url:
            return {
                "status": "healthy",
                "coverage": {
                    "mode": "persistence_plus_recent_cache",
                    "note": "Recent search/export uses persistence.",
                    "api_window_counts": {"enriched_events": 5000, "alerts": 157},
                },
                "observability": {
                    "persistence_storage": {
                        "storage_status": "warning",
                        "free_disk_bytes": 512 * 1024 * 1024,
                        "db_file_bytes": 6 * 1024 * 1024 * 1024,
                        "wal_file_bytes": 128 * 1024 * 1024,
                        "db_max_bytes": 5 * 1024 * 1024 * 1024,
                        "free_disk_warning_bytes": 1024 * 1024 * 1024,
                        "cleanup_status": "success",
                        "storage_reasons": ["free disk below warning threshold"],
                    }
                },
            }
        return {"status": "healthy", "details": "not-json"}

    monkeypatch.setattr(welcome, "st", fake_st)
    monkeypatch.setattr(welcome, "check_service_health", fake_health)

    welcome.render()

    assert "Coverage note: Recent search/export uses persistence." in fake_st.captions
    assert any("recent enriched events: `5000`" in caption for caption in fake_st.captions)
    assert any("SQLite storage pressure detected" in warning for warning in fake_st.warnings)
    assert any("Storage reasons:" in caption for caption in fake_st.captions)


def test_storage_warning_summary_uses_current_top_level_persistence_storage():
    summary = storage_warning_summary({
        "persistence_storage": {
            "storage_status": "critical",
            "free_disk_bytes": 32 * 1024 * 1024,
            "db_file_bytes": 6 * 1024 * 1024 * 1024,
            "db_max_bytes": 5 * 1024 * 1024 * 1024,
            "wal_file_bytes": 0,
            "cleanup_status": "success",
            "free_disk_warning_bytes": 1024 * 1024 * 1024,
            "storage_reasons": ["free disk below critical threshold"],
        }
    })

    assert summary is not None
    assert summary["status"] == "critical"
    assert summary["db_max"] == 5 * 1024 * 1024 * 1024


def test_storage_warning_summary_returns_none_for_ok_storage():
    assert storage_warning_summary({
        "persistence_storage": {
            "storage_status": "ok",
            "free_disk_bytes": 2 * 1024 * 1024 * 1024,
            "db_file_bytes": 10,
            "db_max_bytes": 5 * 1024 * 1024 * 1024,
            "free_disk_warning_bytes": 1024 * 1024 * 1024,
        }
    }) is None
