import json

from scripts import landing_page


def test_landing_page_renders_configured_links(monkeypatch):
    monkeypatch.setenv("SOURCE_CLUSTER_DISPLAY_NAME", "Audit Source")
    monkeypatch.setenv("DESTINATION_CLUSTER_DISPLAY_NAME", "Audit Destination")
    monkeypatch.setenv("AUDIT_TOPIC", "confluent-audit-log-events")
    monkeypatch.setenv("AUDIT_ENRICHED_TOPIC", "audit.enriched.v1")
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setattr(landing_page, "_storage_snapshot", lambda: {
        "storage_status": "warning",
        "storage_mode": "warning",
        "db_file_bytes": 6 * 1024 * 1024 * 1024,
        "current_db_size": 6 * 1024 * 1024 * 1024 + 32 * 1024 * 1024,
        "wal_file_bytes": 32 * 1024 * 1024,
        "free_disk_bytes": 128 * 1024 * 1024,
        "db_max_bytes": 5 * 1024 * 1024 * 1024,
        "cleanup_status": "success",
        "hot_cache_retention_hours": 24,
        "last_rotation_time": "2026-04-27T12:29:45Z",
        "archive_enabled": False,
        "storage_reasons": ["free disk below critical threshold"],
    })

    body = landing_page._html().decode("utf-8")

    assert "AuditLens" in body
    assert "Audit Source" in body
    assert "Audit Destination" in body
    assert "confluent-audit-log-events" in body
    assert "http://localhost:8503" in body
    assert "http://localhost:3000" in body
    assert "http://localhost:9090" in body
    assert "http://localhost:8003/health" in body
    assert "http://localhost:8003/metrics" in body
    assert "audit.enriched.v1" in body
    assert "docker compose logs -f auditlens-forwarder" in body
    assert "bash scripts/verify.sh" in body
    assert "SQLite Storage" in body
    assert "SQLite is a bounded hot cache, not long-term archive" in body
    assert "Showing recent audit intelligence only" in body
    assert "Older audit history requires archive/Tableflow integration" in body
    assert "storage pressure is warning" in body
    assert "Current DB size" in body
    assert "Hot cache retention" in body
    assert "Storage mode" in body
    assert "Last rotation" in body
    assert "Archive enabled" in body
    assert "free disk below critical threshold" in body


def test_landing_status_returns_target_map(monkeypatch):
    monkeypatch.setattr(landing_page, "_probe", lambda url: "ok" if "health" in url else "down")

    statuses = landing_page._statuses()

    assert statuses["health"] == "ok"
    assert statuses["dashboard"] == "down"
    assert set(statuses) == {"dashboard", "grafana", "prometheus", "health", "metrics"}


def test_landing_status_handler_returns_json(monkeypatch):
    class FakeHandler:
        path = "/status"

        def __init__(self):
            self.status_code = None
            self.headers = {}
            self.body = b""
            self.wfile = self

        def send_response(self, status_code):
            self.status_code = status_code

        def send_header(self, key, value):
            self.headers[key] = value

        def end_headers(self):
            pass

        def write(self, payload):
            self.body += payload

    monkeypatch.setattr(landing_page, "_statuses", lambda: {"dashboard": "ok"})
    handler = FakeHandler()

    landing_page.LandingHandler.do_GET(handler)

    assert handler.status_code == 200
    assert handler.headers["Content-Type"] == "application/json"
    assert json.loads(handler.body) == {"dashboard": "ok"}


def test_landing_storage_snapshot_reads_degraded_health_payload(monkeypatch):
    monkeypatch.setattr(landing_page, "_forwarder_health", lambda: {
        "status": "unhealthy",
        "observability": {
            "persistence_storage": {
                "storage_status": "critical",
                "storage_mode": "emergency",
                "db_file_bytes": 10,
                "current_db_size": 30,
                "wal_file_bytes": 20,
                "free_disk_bytes": 30,
                "db_max_bytes": 40,
                "cleanup_status": "success",
                "hot_cache_retention_hours": 24,
                "last_rotation_time": "now",
                "archive_enabled": False,
                "storage_reasons": ["free disk below critical threshold"],
            }
        },
    })

    snapshot = landing_page._storage_snapshot()

    assert snapshot["storage_status"] == "critical"
    assert snapshot["storage_mode"] == "emergency"
    assert snapshot["current_db_size"] == 30
    assert snapshot["free_disk_bytes"] == 30
    assert snapshot["hot_cache_retention_hours"] == 24
    assert snapshot["archive_enabled"] is False
    assert snapshot["storage_reasons"] == ["free disk below critical threshold"]
