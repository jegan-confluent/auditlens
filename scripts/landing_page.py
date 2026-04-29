#!/usr/bin/env python3
"""Local-only AuditLens landing page."""

from __future__ import annotations

import html
import json
import os
import socket
import time
from typing import Any
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PORT = int(os.getenv("LANDING_PORT", "8088"))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8503"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8003"))
SETUP_TIMESTAMP = os.getenv("SETUP_TIMESTAMP") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _topic_list() -> list[str]:
    return [
        _env("AUDIT_RAW_TOPIC", "audit.raw.v1"),
        _env("AUDIT_NORMALIZED_TOPIC", "audit.normalized.v1"),
        _env("AUDIT_ENRICHED_TOPIC", "audit.enriched.v1"),
        _env("AUDIT_SIGNALS_DENIALS_TOPIC", "audit.signals.denials.v1"),
        _env("AUDIT_SIGNALS_HIGHRISK_TOPIC", "audit.signals.highrisk.v1"),
        _env("AUDIT_ALERTS_TOPIC", "audit.alerts.v1"),
        _env("DLQ_TOPIC", "audit.dlq.v1"),
    ]


def _status_targets() -> dict[str, str]:
    return {
        "dashboard": "http://dashboard:8501",
        "grafana": "http://grafana:3000/api/health",
        "prometheus": "http://prometheus:9090/-/ready",
        "health": f"http://auditlens-forwarder:{METRICS_PORT}/health",
        "metrics": f"http://auditlens-forwarder:{METRICS_PORT}/metrics",
    }


def _probe(url: str) -> str:
    try:
        request = Request(url, headers={"User-Agent": "AuditLens landing"})
        with urlopen(request, timeout=2.0) as response:
            return "ok" if 200 <= response.status < 500 else "down"
    except (OSError, TimeoutError, URLError, socket.timeout):
        return "down"


def _statuses() -> dict[str, str]:
    return {name: _probe(url) for name, url in _status_targets().items()}


def _format_bytes(value: int) -> str:
    size = float(max(value, 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(value)} B"


def _forwarder_health() -> dict[str, Any]:
    request = Request(f"http://auditlens-forwarder:{METRICS_PORT}/health", headers={"User-Agent": "AuditLens landing"})
    try:
        with urlopen(request, timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    except (OSError, TimeoutError, URLError, socket.timeout, json.JSONDecodeError):
        return {}


def _storage_snapshot() -> dict[str, Any]:
    health = _forwarder_health()
    observability = health.get("observability") if isinstance(health.get("observability"), dict) else {}
    storage = observability.get("persistence_storage") if isinstance(observability.get("persistence_storage"), dict) else {}
    return {
        "storage_status": storage.get("storage_status", "unknown"),
        "storage_mode": storage.get("storage_mode", "unknown"),
        "db_file_bytes": int(storage.get("db_file_bytes", 0) or 0),
        "current_db_size": int(storage.get("current_db_size", storage.get("db_file_bytes", 0)) or 0),
        "wal_file_bytes": int(storage.get("wal_file_bytes", 0) or 0),
        "free_disk_bytes": int(storage.get("free_disk_bytes", 0) or 0),
        "db_max_bytes": int(storage.get("max_db_size", storage.get("db_max_bytes", 0)) or 0),
        "cleanup_status": storage.get("cleanup_status", "unknown"),
        "hot_cache_retention_hours": int(storage.get("hot_cache_retention_hours", storage.get("rotation_retention_hours", 0)) or 0),
        "last_rotation_time": storage.get("last_rotation_time") or "never",
        "archive_enabled": bool(storage.get("archive_enabled", False)),
        "storage_reasons": storage.get("storage_reasons", []) if isinstance(storage.get("storage_reasons"), list) else [],
    }


def _storage_panel() -> str:
    snapshot = _storage_snapshot()
    status = snapshot["storage_status"]
    badge_class = "critical" if status == "critical" else "warning" if status == "warning" else "ok" if status == "ok" else "neutral"
    reasons = ""
    if snapshot["storage_reasons"]:
        reason_items = "".join(f"<li>{html.escape(reason)}</li>" for reason in snapshot["storage_reasons"])
        reasons = f"<ul>{reason_items}</ul>"
    warning = ""
    if status in {"warning", "critical"}:
        warning = f'<p class="storage-warning">SQLite storage pressure is {html.escape(status)}. Investigate disk capacity or retention before persistence fails.</p>'
    db_limit = _format_bytes(snapshot["db_max_bytes"]) if snapshot["db_max_bytes"] else "n/a"
    retention = f"{snapshot['hot_cache_retention_hours']} hours" if snapshot["hot_cache_retention_hours"] else "bounded by size"
    return f"""
    <section class="panel storage-panel">
      <div class="card-top">
        <h2>SQLite Storage</h2>
        <span class="status {badge_class}">{html.escape(status)}</span>
      </div>
      <p class="storage-truth">SQLite is a bounded hot cache, not long-term archive. Showing recent audit intelligence only. Older audit history requires archive/Tableflow integration.</p>
      {warning}
      <dl>
        <dt>Current DB size</dt><dd>{html.escape(_format_bytes(snapshot['current_db_size']))}</dd>
        <dt>WAL size</dt><dd>{html.escape(_format_bytes(snapshot['wal_file_bytes']))}</dd>
        <dt>Free disk</dt><dd>{html.escape(_format_bytes(snapshot['free_disk_bytes']))}</dd>
        <dt>Max DB size</dt><dd>{html.escape(db_limit)}</dd>
        <dt>Hot cache retention</dt><dd>{html.escape(retention)}</dd>
        <dt>Storage mode</dt><dd>{html.escape(str(snapshot['storage_mode']))}</dd>
        <dt>Last rotation</dt><dd>{html.escape(str(snapshot['last_rotation_time']))}</dd>
        <dt>Archive enabled</dt><dd>{'yes' if snapshot['archive_enabled'] else 'no'}</dd>
        <dt>Cleanup status</dt><dd>{html.escape(str(snapshot['cleanup_status']))}</dd>
      </dl>
      {reasons}
    </section>
    """


def _card(title: str, href: str, description: str, status_key: str) -> str:
    safe_title = html.escape(title)
    safe_href = html.escape(href)
    safe_description = html.escape(description)
    return f"""
    <a class="card" href="{safe_href}" target="_blank" rel="noreferrer">
      <div class="card-top">
        <h2>{safe_title}</h2>
        <span class="status neutral" data-status="{status_key}">checking</span>
      </div>
      <p>{safe_description}</p>
      <code>{safe_href}</code>
    </a>
    """


def _html() -> bytes:
    source_name = html.escape(_env("SOURCE_CLUSTER_DISPLAY_NAME", "Confluent Cloud Audit Logs"))
    destination_name = html.escape(_env("DESTINATION_CLUSTER_DISPLAY_NAME", "AuditLens Destination Cluster"))
    audit_topic = html.escape(_env("AUDIT_TOPIC", "confluent-audit-log-events"))
    api_auth = "enabled" if _env("API_AUTH_ENABLED", "false").lower() == "true" else "disabled"
    topics = "\n".join(f"<li><code>{html.escape(topic)}</code></li>" for topic in _topic_list())
    generated_at = html.escape(SETUP_TIMESTAMP)

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AuditLens</title>
  <style>
    :root {{
      --ink: #17211b;
      --muted: #5a685f;
      --paper: #f5f1e8;
      --card: #fffaf0;
      --line: #ded3bd;
      --green: #16734a;
      --red: #a33b2e;
      --neutral: #77684f;
      --amber: #a06117;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-serif, Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(22,115,74,.16), transparent 36rem),
        linear-gradient(135deg, #f7f0df, #eef4ec);
      min-height: 100vh;
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }}
    .hero {{ display: grid; gap: 10px; margin-bottom: 28px; }}
    .eyebrow {{ text-transform: uppercase; letter-spacing: .16em; color: var(--green); font: 700 12px ui-sans-serif, system-ui; }}
    h1 {{ margin: 0; font-size: clamp(44px, 8vw, 86px); line-height: .92; }}
    .subtitle {{ max-width: 720px; color: var(--muted); font-size: 20px; line-height: 1.45; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 16px; margin: 28px 0; }}
    .card, .panel {{
      background: rgba(255,250,240,.88);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: 0 18px 50px rgba(64, 48, 28, .10);
    }}
    .card {{ display: block; padding: 20px; color: inherit; text-decoration: none; transition: transform .16s ease, border-color .16s ease; }}
    .card:hover {{ transform: translateY(-3px); border-color: var(--green); }}
    .card-top {{ display: flex; align-items: start; justify-content: space-between; gap: 12px; }}
    h2 {{ margin: 0 0 8px; font-size: 22px; }}
    p {{ margin: 0; }}
    code {{ display: block; margin-top: 14px; color: var(--muted); overflow-wrap: anywhere; font-size: 13px; }}
    .status {{ border-radius: 999px; padding: 4px 9px; color: #fff; font: 700 11px ui-sans-serif, system-ui; text-transform: uppercase; }}
    .status.ok {{ background: var(--green); }}
    .status.down, .status.critical {{ background: var(--red); }}
    .status.warning {{ background: var(--amber); }}
    .status.neutral {{ background: var(--neutral); }}
    .panel {{ padding: 22px; }}
    .two {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 16px; }}
    dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 10px 18px; margin: 0; }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; font-weight: 700; overflow-wrap: anywhere; }}
    ul {{ margin: 10px 0 0; padding-left: 20px; }}
    .commands code {{ background: #efe4ce; border-radius: 10px; padding: 10px; }}
    .storage-panel {{ margin-top: 16px; }}
    .storage-truth {{ color: var(--muted); margin: 0 0 14px; max-width: 760px; }}
    .storage-warning {{ color: var(--red); font-weight: 700; margin: 10px 0 14px; }}
    @media (max-width: 800px) {{ .two {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="eyebrow">Local AuditLens Entry Point</div>
      <h1>AuditLens</h1>
      <p class="subtitle">Setup completed. Use this page as the local launch point for the dashboard, health checks, and observability tools.</p>
    </section>

    <section class="grid">
      {_card("Dashboard", f"http://localhost:{DASHBOARD_PORT}", "Search audit events, high-risk activity, denials, and exports.", "dashboard")}
      {_card("Grafana", "http://localhost:3000", "Metrics dashboards for runtime and operational visibility.", "grafana")}
      {_card("Prometheus", "http://localhost:9090", "Raw metrics store and PromQL query surface.", "prometheus")}
      {_card("Forwarder Health", f"http://localhost:{METRICS_PORT}/health", "Readiness, recovery, freshness, and persistence state.", "health")}
      {_card("Forwarder Metrics", f"http://localhost:{METRICS_PORT}/metrics", "Prometheus-format metrics exposed by the forwarder.", "metrics")}
    </section>

    <section class="two">
      <div class="panel">
        <h2>Setup Summary</h2>
        <dl>
          <dt>Source cluster</dt><dd>{source_name}</dd>
          <dt>Destination cluster</dt><dd>{destination_name}</dd>
          <dt>Source audit topic</dt><dd><code>{audit_topic}</code></dd>
          <dt>Dashboard port</dt><dd>{DASHBOARD_PORT}</dd>
          <dt>Forwarder port</dt><dd>{METRICS_PORT}</dd>
          <dt>API auth</dt><dd>{api_auth}</dd>
          <dt>Setup timestamp</dt><dd>{generated_at}</dd>
        </dl>
      </div>
      <div class="panel">
        <h2>Destination Topics</h2>
        <ul>{topics}</ul>
      </div>
    </section>

    {_storage_panel()}

    <section class="panel commands" style="margin-top:16px">
      <h2>Useful Commands</h2>
      <code>docker compose logs -f auditlens-forwarder</code>
      <code>bash scripts/verify.sh</code>
    </section>
  </main>
  <script>
    async function refreshStatus() {{
      try {{
        const response = await fetch('/status', {{cache: 'no-store'}});
        const data = await response.json();
        for (const [name, state] of Object.entries(data)) {{
          document.querySelectorAll(`[data-status="${{name}}"]`).forEach((node) => {{
            node.className = `status ${{state}}`;
            node.textContent = state === 'ok' ? 'online' : 'offline';
          }});
        }}
      }} catch (_err) {{}}
    }}
    refreshStatus();
    setInterval(refreshStatus, 15000);
  </script>
</body>
</html>"""
    return document.encode("utf-8")


class LandingHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/status":
            payload = json.dumps(_statuses()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path not in {"/", "/index.html"}:
            self.send_response(404)
            self.end_headers()
            return
        payload = _html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), LandingHandler)
    print(f"AuditLens landing page listening on {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
