"""HTTP metrics/health server for the AuditLens forwarder.

All runtime singletons (metrics, api_state, etc.) are injected at startup
via start_metrics_server() so this module has no import-time dependency on
audit_forwarder.py.
"""

import csv
import logging
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import orjson

from src.forwarder.config import (
    API_EXPORT_MAX_HOURS,
    API_EXPORT_MAX_ROWS,
    API_MAX_SEARCH_RESULTS,
    AUDIT_TOPIC,
    AUTH_CONFIG,
    DB_WRITE_FLUSH_INTERVAL_SECONDS,
    ENABLE_DB_WRITER,
    EVENT_RETENTION_DAYS,
    GROUP_ID,
    METRICS_PORT,
    PERSISTENCE_CONFIG,
    REPLAY_ENABLED,
    REPLAY_PUBLISH_DERIVED_TOPICS,
)
from src.forwarder.utils import utc_now_iso
from src.metrics.audit_events import audit_event_metrics
from src.product import Role

logger = logging.getLogger()

_version_file = Path(__file__).parent.parent.parent / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "2.1.0"

# ──────────── Runtime singletons — set by start_metrics_server() ────────────
# Mutable dicts (delivery_errors, dlq_stats) are passed by reference so updates
# from the consumer thread are visible immediately.

metrics = None
product_store = None
api_state = None
replay_state = None
authenticator = None
delivery_errors: dict = {"count": 0, "last_error": None}
dlq_stats: dict = {"sent": 0, "failed": 0, "enqueued": 0}

# Functions injected from audit_forwarder at startup
validate_startup_config = None
replay_events = None


# ──────────── Pure helper functions (no external deps) ────────────

def _parse_iso_to_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _compute_db_behind_seconds(last_event_iso: str | None) -> int | None:
    """now - last event timestamp, in whole seconds. None when unknown."""
    last = _parse_iso_to_utc(last_event_iso)
    if last is None:
        return None
    delta = (datetime.now(timezone.utc) - last).total_seconds()
    return int(max(0, delta))


def _classify_db_writer_status(last_write_iso: str | None, error_count: int) -> str:
    """healthy: <60s ago + no consecutive errors;
    degraded: 60-300s ago OR error_count > 0;
    stalled:  >300s ago OR last_write_iso is None.

    Cold start sits in `stalled` until the first successful batch lands
    — matches the Phase 2 spec literally.
    """
    last = _parse_iso_to_utc(last_write_iso)
    if last is None:
        return "stalled"
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age > 300:
        return "stalled"
    if age > 60 or error_count > 0:
        return "degraded"
    return "healthy"


def _is_replay_recommended(consumer_lag: int | None, db_behind_seconds: int | None) -> bool:
    """True iff Kafka is fully consumed AND Postgres is >5min behind —
    the signal that says 'run replay to backfill the missing tail'."""
    if consumer_lag is None or db_behind_seconds is None:
        return False
    return consumer_lag == 0 and db_behind_seconds > 300


def _build_db_writer_block(metrics_data: dict) -> dict:
    """Compose the /health `db_writer` block from a metrics snapshot.

    Each field is wrapped against missing keys / unparseable timestamps;
    the worst possible outcome is `{status: "stalled", ...None}`, never
    a 500.
    """
    try:
        last_write_iso = metrics_data.get("db_last_successful_write")
        last_event_iso = metrics_data.get("db_last_event_timestamp_iso")
        error_count = int(metrics_data.get("db_write_consecutive_error_count") or 0)
        return {
            "last_write_at": last_write_iso,
            "last_event_timestamp": last_event_iso,
            "db_behind_seconds": _compute_db_behind_seconds(last_event_iso),
            "write_error_count": error_count,
            "status": _classify_db_writer_status(last_write_iso, error_count),
        }
    except Exception:
        # Defensive: any unexpected shape returns a stalled-shaped block
        # so the route stays valid JSON.
        return {
            "last_write_at": None,
            "last_event_timestamp": None,
            "db_behind_seconds": None,
            "write_error_count": 0,
            "status": "stalled",
        }


def _request_filters(params: dict) -> dict:
    return {
        "q": (params.get("q", [""])[0] or "").strip(),
        "criticality": (params.get("criticality", [""])[0] or "").strip(),
        "principal": (params.get("principal", [""])[0] or "").strip(),
        "method": (params.get("method", [""])[0] or "").strip(),
        "resource": (params.get("resource", [""])[0] or "").strip(),
        "time_from": (params.get("time_from", [""])[0] or "").strip(),
        "time_to": (params.get("time_to", [""])[0] or "").strip(),
    }


def _request_actor(headers):
    return authenticator.authenticate(headers)


def _normalize_json_keys(obj):
    if isinstance(obj, dict):
        return {str(key): _normalize_json_keys(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_normalize_json_keys(item) for item in obj]
    return obj


# ──────────── metrics server ────────────
class MetricsHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict, headers: dict | None = None):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        try:
            safe_payload = _normalize_json_keys(payload)
            self.wfile.write(orjson.dumps(safe_payload, option=orjson.OPT_INDENT_2))
        except BrokenPipeError:
            # Client disconnected before response completed — normal,
            # happens when healthcheck client closes early. Never re-raise.
            pass
        except TypeError as e:
            logger.warning("Health payload serialization failed: %s", e)
            try:
                fallback = orjson.dumps({"status": "ok", "error": "serialization_failed"})
                self.wfile.write(fallback)
            except Exception:
                pass
        except Exception as e:
            logger.debug("Health endpoint send error (ignored): %s", e)
            pass

    def _send_bytes(self, status_code: int, content_type: str, payload: bytes, headers: dict | None = None):
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(payload)

    def _json_error(self, status_code: int, message: str):
        self._send_json(status_code, {
            "error": message,
            "timestamp": utc_now_iso(),
        })

    def _record_api_audit(self, actor, action: str, endpoint: str, status_code: int, filters: dict, denied_reason: str | None = None):
        if product_store and PERSISTENCE_CONFIG.enabled:
            try:
                product_store.record_api_audit(
                    actor_id=actor.actor_id if actor else None,
                    role=actor.role.value if actor else None,
                    action=action,
                    endpoint=endpoint,
                    status_code=status_code,
                    remote_addr=self.client_address[0] if self.client_address else None,
                    user_agent=self.headers.get("User-Agent"),
                    filters=filters,
                    denied_reason=denied_reason,
                )
            except Exception as exc:
                logger.warning("Failed to record API audit log: %s", exc)

    def _authorize_request(self, endpoint: str, params: dict, export: bool = False):
        auth_result = _request_actor(self.headers)
        filters = _request_filters(params)
        if not auth_result.ok:
            metrics.record_api_auth_failure()
            self._record_api_audit(None, "authenticate", endpoint, auth_result.status_code, filters, auth_result.error)
            self._json_error(auth_result.status_code, auth_result.error or "unauthorized")
            return None

        actor = auth_result.actor
        assert actor is not None
        permission = authenticator.require_export(actor) if export else authenticator.require_view(actor)
        if not permission.ok:
            if export:
                metrics.record_export_denied()
            self._record_api_audit(actor, "authorize", endpoint, permission.status_code, filters, permission.error)
            self._json_error(permission.status_code, permission.error or "forbidden")
            return None

        return actor

    def _search_records(self, filters: dict, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_enriched(filters, actor, limit), "persistence"
        snapshot = api_state.snapshot()
        params = {k: [v] for k, v in filters.items() if v}
        return [
            event for event in snapshot["enriched_events"]
            if actor.scope_allows(event.get("organization_id"), event.get("environment_id"), event.get("cluster_id"))
            and self._match_event(event, params)
        ][:limit], "memory"

    def _high_risk_records(self, filters: dict, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_high_risk(filters, actor, limit), "persistence"
        snapshot = api_state.snapshot()
        params = {k: [v] for k, v in filters.items() if v}
        return [
            event for event in snapshot["high_risk_events"]
            if actor.scope_allows(event.get("organization_id"), event.get("environment_id"), event.get("cluster_id"))
            and self._match_event(event, params)
        ][:limit], "memory"

    def _denial_records(self, actor, limit: int):
        if product_store and PERSISTENCE_CONFIG.enabled and product_store.health().get("healthy"):
            return product_store.query_denials(actor, limit), "persistence"
        snapshot = api_state.snapshot()
        return [
            item for item in snapshot["denial_summaries"]
            if actor.scope_allows(
                (item.get("organization_ids") or [None])[0],
                (item.get("environment_ids") or [None])[0],
                (item.get("cluster_ids") or [None])[0],
            )
        ][:limit], "memory"

    def _validate_export_window(self, filters: dict) -> tuple[bool, str | None]:
        if not filters.get("time_from") or not filters.get("time_to"):
            return True, None
        try:
            start = datetime.fromisoformat(filters["time_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(filters["time_to"].replace("Z", "+00:00"))
        except ValueError:
            return False, "invalid export time window"
        hours = (end - start).total_seconds() / 3600
        if hours > API_EXPORT_MAX_HOURS:
            return False, f"export window exceeds {API_EXPORT_MAX_HOURS} hours"
        return True, None

    def _health_payload(self):
        metrics_data = metrics.get_metrics()
        snapshot = api_state.snapshot()
        replay_snapshot = replay_state.snapshot()
        startup_config = validate_startup_config()

        idle_seconds = metrics_data['idle_seconds']
        error_count = metrics_data['error_count']
        processed = metrics_data['processed_messages_total']
        consumer_state = metrics_data.get("consumer_state", "unknown")
        consecutive_errors = metrics_data.get("consecutive_error_count", 0)
        is_idle = (
            consumer_state == "connected"
            and consecutive_errors == 0
            and metrics_data['uptime_seconds'] > 60
            and idle_seconds > 60
        )
        runtime_consumer_state = "idle" if is_idle else consumer_state
        is_healthy = True
        reasons = []

        if not startup_config["valid"]:
            is_healthy = False
            reasons.append("Startup configuration is invalid")
        if idle_seconds > 300 and not is_idle:
            is_healthy = False
            reasons.append(f"Idle for {idle_seconds:.0f}s (> 300s)")
        if processed > 0 and error_count / processed > 0.1:
            is_healthy = False
            reasons.append(f"High error rate: {error_count}/{processed} ({error_count/processed*100:.1f}%)")

        payload = {
            "status": "healthy" if is_healthy else "unhealthy",
            "state": runtime_consumer_state,
            "timestamp": utc_now_iso(),
            "version": VERSION,
            "uptime_seconds": metrics_data['uptime_seconds'],
            "processed_total": processed,
            "error_count": error_count,
            "idle_seconds": idle_seconds,
            "consumer_lag": metrics_data['consumer_lag_total'],
            "consumer_lag_by_partition": metrics_data['consumer_lag_by_partition'],
            "processing_rate": metrics_data['processing_rate_per_second'],
            "record_queue_depth": metrics_data.get('record_queue_depth', 0),
            "record_queue_capacity": metrics_data.get('record_queue_capacity', 0),
            "queues": metrics_data.get("priority_queue_depths", {
                "critical": 0, "normal": 0, "bulk": 0, "catalog": 0,
            }),
            "noise_short_circuited_total": metrics_data.get("noise_short_circuited_total", 0),
            "noise_persist_wait_timeouts_total": metrics_data.get("noise_persist_wait_timeouts_total", 0),
            "dry_run_suppressed_total": metrics_data.get("dry_run_suppressed_total", 0),
            # ── DB-writer freshness / replay-recommended ──
            # Computed defensively off the in-memory metrics snapshot.
            # Every helper below returns a safe default on bad input so
            # this block never raises and /health stays <100ms.
            "db_writer": _build_db_writer_block(metrics_data),
            "replay_recommended": _is_replay_recommended(
                metrics_data.get("consumer_lag_total"),
                _compute_db_behind_seconds(metrics_data.get("db_last_event_timestamp_iso")),
            ),
            "freshness": {
                "last_enriched_event_time": snapshot["last_enriched_event_time"],
                "last_enriched_ingest_at": snapshot["last_enriched_ingest_at"],
                "last_denial_flush_at": snapshot["last_denial_flush_at"],
                "last_committed_at": metrics_data.get("last_committed_at"),
            },
            "coverage": {
                "mode": "persistence_plus_recent_cache" if product_store and PERSISTENCE_CONFIG.enabled else "recent_in_memory_plus_kafka",
                "note": (
                    "Recent search/export uses persistence when healthy. "
                    "If persistence is unavailable, API falls back to recent in-memory cache with reduced durability."
                    if product_store and PERSISTENCE_CONFIG.enabled else snapshot["coverage_note"]
                ),
                "api_window_counts": {
                    "enriched_events": len(snapshot["enriched_events"]),
                    "high_risk_events": len(snapshot["high_risk_events"]),
                    "denial_summaries": len(snapshot["denial_summaries"]),
                    "alerts": len(snapshot["alerts"]),
                },
            },
            "offset_recovery": {
                "model": "consumer_group_only",
                "commit_behavior": "commit only after persistence success and Kafka producer flush without delivery errors",
                "delivery_semantics": "at_least_once",
                "duplicate_risk": "replay can occur after crash or rebalance between downstream success and offset commit",
            },
            "recovery": {
                "replay_available": REPLAY_ENABLED,
                "replay_in_progress": replay_snapshot["in_progress"],
                "last_replay_started_at": replay_snapshot["started_at"],
                "last_replay_completed_at": replay_snapshot["completed_at"],
                "last_replay_success_at": replay_snapshot["last_success_at"],
                "last_replay_error": replay_snapshot["last_error"],
                "replay_source_mode": replay_snapshot["source_mode"],
                "replay_window_mode": replay_snapshot["window_mode"],
            },
            "observability": {
                "offset_commits_total": metrics_data.get("offset_commits_total", 0),
                "offset_commit_failures_total": metrics_data.get("offset_commit_failures_total", 0),
                "rebalance_count": metrics_data.get("rebalance_count", 0),
                "restart_count": metrics_data.get("restart_count", 0),
                "parse_error_count": metrics_data.get("parse_error_count", 0),
                "dlq_sent_total": dlq_stats["sent"],
                "dlq_failed_total": dlq_stats["failed"],
                "api_auth_failures_total": metrics_data.get("api_auth_failures_total", 0),
                "export_requests_total": metrics_data.get("export_requests_total", 0),
                "export_denied_total": metrics_data.get("export_denied_total", 0),
                "replay_runs_total": metrics_data.get("replay_runs_total", 0),
                "replay_failures_total": metrics_data.get("replay_failures_total", 0),
                "replay_records_processed_total": metrics_data.get("replay_records_processed_total", 0),
                "consumer_runtime": {
                    "poll_count": metrics_data.get("poll_count", 0),
                    "empty_poll_count": metrics_data.get("empty_poll_count", 0),
                    "records_consumed_total": metrics_data.get("records_consumed_total", 0),
                    "retry_count": metrics_data.get("retry_count", 0),
                    "consecutive_error_count": metrics_data.get("consecutive_error_count", 0),
                    "last_error": metrics_data.get("last_error"),
                    "last_error_at": metrics_data.get("last_error_at"),
                    "last_successful_poll": metrics_data.get("last_successful_poll"),
                    "backoff_seconds": metrics_data.get("backoff_seconds", 0),
                    "consumer_state": runtime_consumer_state,
                },
                "db_writer": {
                    "enabled": ENABLE_DB_WRITER,
                    "db_write_success_total": metrics_data.get("db_write_success_total", 0),
                    "db_write_error_total": metrics_data.get("db_write_error_total", 0),
                    "db_write_batch_size": metrics_data.get("db_write_batch_size", 0),
                    "db_last_successful_write": metrics_data.get("db_last_successful_write"),
                    "db_writer_state": metrics_data.get("db_writer_state", "disabled"),
                    "db_last_error": metrics_data.get("db_last_error"),
                    "db_last_cleanup_at": metrics_data.get("db_last_cleanup_at"),
                    "db_last_cleanup_deleted_count": metrics_data.get("db_last_cleanup_deleted_count", 0),
                    "retention_days": EVENT_RETENTION_DAYS,
                    "flush_interval_seconds": DB_WRITE_FLUSH_INTERVAL_SECONDS,
                },
                "signal_counts": metrics_data.get("signal_counts", {}),
                "data_quality": metrics_data.get("data_quality", {}),
                "persistence_storage": metrics_data.get("persistence_status", {}),
            },
            "components": [
                {
                    "name": "config",
                    "status": "healthy" if startup_config["valid"] else "unhealthy",
                    "last_check": utc_now_iso(),
                    "details": {
                        "missing_required": startup_config["missing_required"],
                        "duplicate_topics": startup_config["duplicate_topics"],
                        "invalid_values": startup_config["invalid_values"],
                    },
                },
                {
                    "name": "consumer",
                    "status": "idle" if is_idle else ("healthy" if idle_seconds <= 300 else "degraded"),
                    "last_check": utc_now_iso(),
                    "details": {
                        "group_id": GROUP_ID,
                        "source_topic": AUDIT_TOPIC,
                        "consumer_lag": metrics_data['consumer_lag_total'],
                        "state": runtime_consumer_state,
                        "poll_count": metrics_data.get("poll_count", 0),
                        "empty_poll_count": metrics_data.get("empty_poll_count", 0),
                        "records_consumed_total": metrics_data.get("records_consumed_total", 0),
                        "retry_count": metrics_data.get("retry_count", 0),
                        "consecutive_error_count": metrics_data.get("consecutive_error_count", 0),
                        "last_error": metrics_data.get("last_error"),
                        "last_successful_poll": metrics_data.get("last_successful_poll"),
                        "backoff_seconds": metrics_data.get("backoff_seconds", 0),
                    },
                },
                {
                    "name": "producer",
                    "status": "healthy" if delivery_errors["count"] == 0 else "degraded",
                    "last_check": utc_now_iso(),
                    "details": {
                        "delivery_errors": delivery_errors["count"],
                        "last_delivery_error": delivery_errors["last_error"],
                        "delivery_attempts_by_topic": metrics_data.get("delivery_attempts_by_topic", {}),
                        "delivery_failures_by_topic": metrics_data.get("delivery_failures_by_topic", {}),
                    },
                },
                {
                    "name": "persistence",
                    "status": "healthy" if metrics_data.get("persistence_status", {}).get("healthy") else "degraded",
                    "last_check": utc_now_iso(),
                    "details": metrics_data.get("persistence_status", {}),
                },
                {
                    "name": "api_auth",
                    "status": "healthy" if not AUTH_CONFIG.enabled or AUTH_CONFIG.tokens else "unhealthy",
                    "last_check": utc_now_iso(),
                    "details": {
                        "enabled": AUTH_CONFIG.enabled,
                        "token_count": len(AUTH_CONFIG.tokens),
                    },
                },
                {
                    "name": "replay",
                    "status": "degraded" if replay_snapshot["in_progress"] else "healthy",
                    "last_check": utc_now_iso(),
                    "details": replay_snapshot,
                },
            ],
        }
        try:
            from src.product.actor_enrichment import _confluent_identity_enricher  # noqa: PLC0415
            _enricher = _confluent_identity_enricher()
            if _enricher is not None:
                _enricher_stats = _enricher.get_stats()
                _enricher_partial = _enricher_stats.get("refresh_partial", False)
                payload["components"].append({
                    "name": "identity_enricher",
                    "status": "warning" if _enricher_partial else "healthy",
                    "last_check": utc_now_iso(),
                    "details": _enricher_stats,
                })
        except Exception:
            pass
        if reasons:
            payload["reasons"] = reasons
        return (200 if is_healthy else 503), payload

    def _match_event(self, event: dict, params: dict) -> bool:
        q = (params.get("q", [""])[0] or "").strip().lower()
        if q:
            haystack = " ".join(str(event.get(field, "") or "") for field in (
                "id", "principal", "principal_normalized", "principal_type",
                "methodName", "resourceName", "authzResourceName",
                "resultStatus", "result_message", "cluster_id", "environment_id",
            )).lower()
            if q not in haystack:
                return False

        for field, param in (
            ("criticality", "criticality"),
            ("principal_normalized", "principal"),
            ("methodName", "method"),
            ("resourceName", "resource"),
        ):
            value = (params.get(param, [""])[0] or "").strip().lower()
            if value and value not in str(event.get(field, "") or "").lower():
                if field == "resourceName" and value not in str(event.get("authzResourceName", "") or "").lower():
                    return False
                if field != "resourceName":
                    return False
        return True

    def _limit_from_params(self, params: dict, default: int = 100) -> int:
        try:
            return max(1, min(int(params.get("limit", [str(default)])[0]), API_MAX_SEARCH_RESULTS))
        except ValueError:
            return default

    def _serialize_export_csv(self, rows: list[dict]) -> bytes:
        if not rows:
            return b""
        fieldnames = sorted({key for row in rows for key in row.keys()})
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/metrics':
            # Get current metrics
            metrics_data = metrics.get_metrics()

            # Format metrics in Prometheus format
            prometheus_metrics = []
            prometheus_metrics.append(f"# HELP audit_forwarder_uptime_seconds Uptime of the forwarder in seconds")
            prometheus_metrics.append(f"# TYPE audit_forwarder_uptime_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_uptime_seconds {metrics_data['uptime_seconds']}")

            prometheus_metrics.append(f"# HELP audit_forwarder_processed_messages_total Total number of messages processed")
            prometheus_metrics.append(f"# TYPE audit_forwarder_processed_messages_total counter")
            prometheus_metrics.append(f"audit_forwarder_processed_messages_total {metrics_data['processed_messages_total']}")

            prometheus_metrics.append(f"# HELP audit_forwarder_processing_rate_per_second Rate of messages processed per second")
            prometheus_metrics.append(f"# TYPE audit_forwarder_processing_rate_per_second gauge")
            prometheus_metrics.append(f"audit_forwarder_processing_rate_per_second {metrics_data['processing_rate_per_second']}")

            prometheus_metrics.append(f"# HELP audit_forwarder_error_count_total Total number of processing errors")
            prometheus_metrics.append(f"# TYPE audit_forwarder_error_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_error_count_total {metrics_data['error_count']}")

            prometheus_metrics.append(f"# HELP audit_forwarder_idle_seconds Seconds since last message was processed")
            prometheus_metrics.append(f"# TYPE audit_forwarder_idle_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_idle_seconds {metrics_data['idle_seconds']}")

            prometheus_metrics.append(f"# HELP audit_forwarder_consumer_lag_total Total consumer lag across all partitions")
            prometheus_metrics.append(f"# TYPE audit_forwarder_consumer_lag_total gauge")
            prometheus_metrics.append(f"audit_forwarder_consumer_lag_total {metrics_data['consumer_lag_total']}")

            # Add partition-specific lag metrics
            prometheus_metrics.append(f"# HELP audit_forwarder_consumer_lag Consumer lag by partition")
            prometheus_metrics.append(f"# TYPE audit_forwarder_consumer_lag gauge")
            for partition, lag in metrics_data['consumer_lag_by_partition'].items():
                prometheus_metrics.append(f"audit_forwarder_consumer_lag{{partition=\"{partition}\"}} {lag}")

            prometheus_metrics.append("# HELP audit_forwarder_offset_commits_total Successful offset commits")
            prometheus_metrics.append("# TYPE audit_forwarder_offset_commits_total counter")
            prometheus_metrics.append(f"audit_forwarder_offset_commits_total {metrics_data['offset_commits_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_offset_commit_failures_total Failed offset commits")
            prometheus_metrics.append("# TYPE audit_forwarder_offset_commit_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_offset_commit_failures_total {metrics_data['offset_commit_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_rebalance_total Consumer rebalance callbacks")
            prometheus_metrics.append("# TYPE audit_forwarder_rebalance_total counter")
            prometheus_metrics.append(f"audit_forwarder_rebalance_total {metrics_data['rebalance_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_restart_total Forwarder startups recorded in persistence")
            prometheus_metrics.append("# TYPE audit_forwarder_restart_total counter")
            prometheus_metrics.append(f"audit_forwarder_restart_total {metrics_data['restart_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_parse_errors_total Parse errors")
            prometheus_metrics.append("# TYPE audit_forwarder_parse_errors_total counter")
            prometheus_metrics.append(f"audit_forwarder_parse_errors_total {metrics_data['parse_error_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_writes_total Successful persistence writes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_writes_total counter")
            prometheus_metrics.append(f"audit_forwarder_persistence_writes_total {metrics_data['persistence_write_success_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_failures_total Persistence write failures")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_persistence_failures_total {metrics_data['persistence_write_failures']}")

            prometheus_metrics.append("# HELP audit_forwarder_api_auth_failures_total API auth failures")
            prometheus_metrics.append("# TYPE audit_forwarder_api_auth_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_api_auth_failures_total {metrics_data['api_auth_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_export_requests_total API export requests")
            prometheus_metrics.append("# TYPE audit_forwarder_export_requests_total counter")
            prometheus_metrics.append(f"audit_forwarder_export_requests_total {metrics_data['export_requests_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_export_denied_total Denied export requests")
            prometheus_metrics.append("# TYPE audit_forwarder_export_denied_total counter")
            prometheus_metrics.append(f"audit_forwarder_export_denied_total {metrics_data['export_denied_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_runs_total Replay runs started")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_runs_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_runs_total {metrics_data['replay_runs_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_failures_total Replay failures")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_failures_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_failures_total {metrics_data['replay_failures_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_records_processed_total Replay records processed")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_records_processed_total counter")
            prometheus_metrics.append(f"audit_forwarder_replay_records_processed_total {metrics_data['replay_records_processed_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_replay_in_progress Replay in-progress indicator")
            prometheus_metrics.append("# TYPE audit_forwarder_replay_in_progress gauge")
            prometheus_metrics.append(f"audit_forwarder_replay_in_progress {1 if metrics_data['replay_in_progress'] else 0}")

            prometheus_metrics.append("# HELP audit_forwarder_poll_count_total Kafka consume poll attempts")
            prometheus_metrics.append("# TYPE audit_forwarder_poll_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_poll_count_total {metrics_data['poll_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_empty_poll_count_total Kafka consume polls that returned no records")
            prometheus_metrics.append("# TYPE audit_forwarder_empty_poll_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_empty_poll_count_total {metrics_data['empty_poll_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_records_consumed_total Kafka records consumed before downstream processing")
            prometheus_metrics.append("# TYPE audit_forwarder_records_consumed_total counter")
            prometheus_metrics.append(f"audit_forwarder_records_consumed_total {metrics_data['records_consumed_total']}")

            prometheus_metrics.append("# HELP audit_forwarder_retry_count_total Kafka retry/backoff attempts")
            prometheus_metrics.append("# TYPE audit_forwarder_retry_count_total counter")
            prometheus_metrics.append(f"audit_forwarder_retry_count_total {metrics_data['retry_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_consecutive_error_count Consecutive Kafka/runtime errors")
            prometheus_metrics.append("# TYPE audit_forwarder_consecutive_error_count gauge")
            prometheus_metrics.append(f"audit_forwarder_consecutive_error_count {metrics_data['consecutive_error_count']}")

            prometheus_metrics.append("# HELP audit_forwarder_backoff_seconds Current Kafka/runtime backoff sleep")
            prometheus_metrics.append("# TYPE audit_forwarder_backoff_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_backoff_seconds {metrics_data['backoff_seconds']}")

            consumer_state_value = {"connected": 0, "idle": 0, "retrying": 1, "backoff": 2, "degraded": 3, "starting": 4}.get(metrics_data.get("consumer_state"), 4)
            prometheus_metrics.append("# HELP audit_forwarder_consumer_state Consumer state (0=connected_or_idle,1=retrying,2=backoff,3=degraded,4=starting)")
            prometheus_metrics.append("# TYPE audit_forwarder_consumer_state gauge")
            prometheus_metrics.append(f"audit_forwarder_consumer_state {consumer_state_value}")

            last_poll = metrics_data.get("last_successful_poll")
            last_poll_ts = int(datetime.fromisoformat(last_poll.replace('Z', '+00:00')).timestamp()) if last_poll else 0
            prometheus_metrics.append("# HELP audit_forwarder_last_successful_poll_timestamp_seconds Unix timestamp of last successful Kafka poll")
            prometheus_metrics.append("# TYPE audit_forwarder_last_successful_poll_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_last_successful_poll_timestamp_seconds {last_poll_ts}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_success_total Successful DB write batches")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_success_total counter")
            prometheus_metrics.append(f"audit_forwarder_db_write_success_total {metrics_data.get('db_write_success_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_error_total Failed DB write batches")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_error_total counter")
            prometheus_metrics.append(f"audit_forwarder_db_write_error_total {metrics_data.get('db_write_error_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_db_write_batch_size Last DB write batch size")
            prometheus_metrics.append("# TYPE audit_forwarder_db_write_batch_size gauge")
            prometheus_metrics.append(f"audit_forwarder_db_write_batch_size {metrics_data.get('db_write_batch_size', 0)}")

            db_state_value = {"disabled": 0, "connected": 1, "retrying": 2, "backoff": 3, "degraded": 3}.get(metrics_data.get("db_writer_state"), 0)
            prometheus_metrics.append("# HELP audit_forwarder_db_writer_state DB writer state (0=disabled,1=connected,2=retrying,3=backoff)")
            prometheus_metrics.append("# TYPE audit_forwarder_db_writer_state gauge")
            prometheus_metrics.append(f"audit_forwarder_db_writer_state {db_state_value}")

            last_db_write = metrics_data.get("db_last_successful_write")
            last_db_write_ts = int(datetime.fromisoformat(last_db_write.replace('Z', '+00:00')).timestamp()) if last_db_write else 0
            prometheus_metrics.append("# HELP audit_forwarder_db_last_successful_write_timestamp_seconds Unix timestamp of last successful DB write")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_successful_write_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_successful_write_timestamp_seconds {last_db_write_ts}")

            last_db_cleanup = metrics_data.get("db_last_cleanup_at")
            last_db_cleanup_ts = int(datetime.fromisoformat(last_db_cleanup.replace('Z', '+00:00')).timestamp()) if last_db_cleanup else 0
            prometheus_metrics.append("# HELP audit_forwarder_db_last_cleanup_timestamp_seconds Last successful DB retention cleanup timestamp")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_cleanup_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_cleanup_timestamp_seconds {last_db_cleanup_ts}")
            prometheus_metrics.append("# HELP audit_forwarder_db_last_cleanup_deleted_count Rows deleted by the last DB retention cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_db_last_cleanup_deleted_count gauge")
            prometheus_metrics.append(f"audit_forwarder_db_last_cleanup_deleted_count {metrics_data.get('db_last_cleanup_deleted_count', 0)}")
            prometheus_metrics.append("# HELP audit_forwarder_produce_retry_exhausted_total Produce retries exhausted before success")
            prometheus_metrics.append("# TYPE audit_forwarder_produce_retry_exhausted_total counter")
            prometheus_metrics.append(f"audit_forwarder_produce_retry_exhausted_total {metrics_data.get('produce_retry_exhausted_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_delivery_attempts_total Delivery attempts by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_attempts_total counter")
            for topic, count in metrics_data['delivery_attempts_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_attempts_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_delivery_failures_total Delivery failures by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_failures_total counter")
            for topic, count in metrics_data['delivery_failures_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_failures_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_delivery_success_total Successful deliveries by topic")
            prometheus_metrics.append("# TYPE audit_forwarder_delivery_success_total counter")
            for topic, count in metrics_data['delivery_success_by_topic'].items():
                prometheus_metrics.append(f'audit_forwarder_delivery_success_total{{topic="{topic}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_signal_total Signals emitted by type")
            prometheus_metrics.append("# TYPE audit_forwarder_signal_total counter")
            for signal_type, count in metrics_data['signal_counts'].items():
                prometheus_metrics.append(f'audit_forwarder_signal_total{{type="{signal_type}"}} {count}')

            prometheus_metrics.append("# HELP audit_forwarder_data_quality_total Data quality counters")
            prometheus_metrics.append("# TYPE audit_forwarder_data_quality_total counter")
            for metric_name, count in metrics_data['data_quality'].items():
                prometheus_metrics.append(f'audit_forwarder_data_quality_total{{metric="{metric_name}"}} {count}')

            persistence_status = metrics_data.get("persistence_status", {})
            prometheus_metrics.append("# HELP audit_forwarder_persistence_db_file_bytes SQLite DB file size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_db_file_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_db_file_bytes {persistence_status.get('db_file_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_storage_db_size_bytes SQLite hot-cache DB plus WAL size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_db_size_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_storage_db_size_bytes {persistence_status.get('current_db_size', persistence_status.get('db_file_bytes', 0))}")

            storage_mode_value = {"normal": 0, "warning": 1, "critical": 2, "emergency": 3}.get(persistence_status.get('storage_mode', 'normal'), 0)
            prometheus_metrics.append("# HELP audit_forwarder_storage_mode SQLite storage mode (0=normal,1=warning,2=critical,3=emergency)")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_mode gauge")
            prometheus_metrics.append(f"audit_forwarder_storage_mode {storage_mode_value}")

            prometheus_metrics.append("# HELP audit_forwarder_rotation_total SQLite hot-cache rotations completed")
            prometheus_metrics.append("# TYPE audit_forwarder_rotation_total counter")
            prometheus_metrics.append(f"audit_forwarder_rotation_total {persistence_status.get('rotation_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_rotation_duration_ms Last SQLite hot-cache rotation duration in milliseconds")
            prometheus_metrics.append("# TYPE audit_forwarder_rotation_duration_ms gauge")
            prometheus_metrics.append(f"audit_forwarder_rotation_duration_ms {persistence_status.get('rotation_duration_ms', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_storage_write_dropped_total Low-priority persistence writes dropped by storage guard")
            prometheus_metrics.append("# TYPE audit_forwarder_storage_write_dropped_total counter")
            prometheus_metrics.append(f"audit_forwarder_storage_write_dropped_total {persistence_status.get('storage_write_dropped_total', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_wal_file_bytes SQLite WAL file size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_wal_file_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_wal_file_bytes {persistence_status.get('wal_file_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_bytes Free disk bytes for the persistence path")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_bytes {persistence_status.get('free_disk_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_db_max_bytes Configured maximum SQLite DB size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_db_max_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_db_max_bytes {persistence_status.get('db_max_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_wal_max_bytes Configured maximum SQLite WAL size in bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_wal_max_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_wal_max_bytes {persistence_status.get('wal_max_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_warning_bytes Warning threshold for free disk bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_warning_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_warning_bytes {persistence_status.get('free_disk_warning_bytes', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_free_disk_critical_bytes Critical threshold for free disk bytes")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_free_disk_critical_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_free_disk_critical_bytes {persistence_status.get('free_disk_critical_bytes', 0)}")

            storage_status_value = {"ok": 0, "warning": 1, "critical": 2}.get(persistence_status.get('storage_status', 'ok'), 0)
            prometheus_metrics.append("# HELP audit_forwarder_persistence_storage_status SQLite storage status (0=ok,1=warning,2=critical)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_storage_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_storage_status {storage_status_value}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_cleanup_deleted_rows Rows deleted by the last persistence cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_cleanup_deleted_rows gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_cleanup_deleted_rows {persistence_status.get('last_cleanup_deleted_rows', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_size_cleanup_deleted_rows_total Rows deleted by the last size-pressure cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_size_cleanup_deleted_rows_total gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_size_cleanup_deleted_rows_total {persistence_status.get('last_cleanup_size_deleted_rows', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_sqlite_reclaimable_bytes SQLite bytes that can be reclaimed by successful VACUUM")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_sqlite_reclaimable_bytes gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_sqlite_reclaimable_bytes {persistence_status.get('sqlite_reclaimable_bytes', 0)}")

            cleanup_strategy = str(persistence_status.get('last_cleanup_strategy') or 'none').replace('\\', '\\\\').replace('"', '\\"')
            prometheus_metrics.append("# HELP audit_forwarder_persistence_cleanup_strategy Last persistence cleanup strategy as an info-style metric")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_cleanup_strategy gauge")
            prometheus_metrics.append(f'audit_forwarder_persistence_cleanup_strategy{{strategy="{cleanup_strategy}"}} 1')

            configured_retention_hours = {
                "enriched_events": PERSISTENCE_CONFIG.enriched_retention_days * 24,
                "high_risk_events": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "denial_summaries": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "alerts": PERSISTENCE_CONFIG.alerts_retention_days * 24,
                "api_audit_log": PERSISTENCE_CONFIG.audit_retention_days * 24,
            }
            effective_retention_hours = persistence_status.get('effective_retention_hours') or {}
            adaptive_limited = 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_effective_retention_hours Effective SQLite retention window after adaptive size pressure")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_effective_retention_hours gauge")
            for table, configured_hours in configured_retention_hours.items():
                effective_hours = int(effective_retention_hours.get(table, configured_hours))
                if effective_hours < configured_hours:
                    adaptive_limited = 1
                prometheus_metrics.append(
                    f'audit_forwarder_persistence_effective_retention_hours{{table="{table}"}} {effective_hours}'
                )

            prometheus_metrics.append("# HELP audit_forwarder_persistence_adaptive_retention_limited Whether adaptive retention shortened any table below configured retention")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_adaptive_retention_limited gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_adaptive_retention_limited {adaptive_limited}")

            cleanup_at = persistence_status.get('last_cleanup_at')
            cleanup_ts = int(datetime.fromisoformat(cleanup_at.replace('Z', '+00:00')).timestamp()) if cleanup_at else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_cleanup_timestamp_seconds Unix timestamp of the last persistence cleanup")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_cleanup_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_cleanup_timestamp_seconds {cleanup_ts}")

            cleanup_status_value = persistence_status.get('cleanup_status')
            cleanup_status = 0 if cleanup_status_value == 'failure' else 1
            prometheus_metrics.append("# HELP audit_forwarder_persistence_cleanup_status Persistence cleanup health status (1=healthy or not yet failed)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_cleanup_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_cleanup_status {cleanup_status}")

            checkpoint_at = persistence_status.get('last_checkpoint_at')
            checkpoint_ts = int(datetime.fromisoformat(checkpoint_at.replace('Z', '+00:00')).timestamp()) if checkpoint_at else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_last_checkpoint_timestamp_seconds Unix timestamp of the last WAL checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_last_checkpoint_timestamp_seconds gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_last_checkpoint_timestamp_seconds {checkpoint_ts}")

            checkpoint_status = 1 if persistence_status.get('last_checkpoint_status') == 'success' else 0
            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_status WAL checkpoint success status (1=success)")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_status gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_status {checkpoint_status}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_busy SQLite WAL checkpoint busy flag")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_busy gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_busy {persistence_status.get('last_checkpoint_busy', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpoint_log_frames SQLite WAL frames seen at last checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpoint_log_frames gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpoint_log_frames {persistence_status.get('last_checkpoint_log_frames', 0)}")

            prometheus_metrics.append("# HELP audit_forwarder_persistence_checkpointed_frames SQLite WAL frames checkpointed at last checkpoint")
            prometheus_metrics.append("# TYPE audit_forwarder_persistence_checkpointed_frames gauge")
            prometheus_metrics.append(f"audit_forwarder_persistence_checkpointed_frames {persistence_status.get('last_checkpoint_checkpointed_frames', 0)}")

            # Add audit event metrics
            prometheus_metrics.append("")
            prometheus_metrics.append(audit_event_metrics.format_prometheus())

            response = "\n".join(prometheus_metrics)

            self._send_bytes(200, 'text/plain', response.encode())
        elif parsed.path in {'/health', '/api/v1/health'}:
            if parsed.path == '/api/v1/health':
                actor = self._authorize_request(parsed.path, params, export=False)
                if actor is None:
                    return
                status_code, payload = self._health_payload()
                self._record_api_audit(actor, "health", parsed.path, status_code, {})
                self._send_json(status_code, payload)
            else:
                status_code, payload = self._health_payload()
                self._send_json(status_code, payload)
        elif parsed.path == '/api/v1/events/search':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            filters = _request_filters(params)
            matches, source = self._search_records(filters, actor, self._limit_from_params(params))
            payload = {
                "items": matches,
                "count": len(matches),
                "coverage_note": "search served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            }
            self._record_api_audit(actor, "search", parsed.path, 200, filters)
            self._send_json(200, payload)
        elif parsed.path == '/api/v1/events/high-risk':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            filters = _request_filters(params)
            matches, source = self._high_risk_records(filters, actor, self._limit_from_params(params, default=50))
            self._send_json(200, {
                "items": matches,
                "count": len(matches),
                "coverage_note": "high-risk search served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            })
            self._record_api_audit(actor, "list_high_risk", parsed.path, 200, filters)
        elif parsed.path == '/api/v1/signals/denials':
            actor = self._authorize_request(parsed.path, params, export=False)
            if actor is None:
                return
            limit = self._limit_from_params(params, default=50)
            items, source = self._denial_records(actor, limit)
            self._send_json(200, {
                "items": items,
                "count": len(items),
                "coverage_note": "denial summaries served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                "source": source,
            })
            self._record_api_audit(actor, "list_denials", parsed.path, 200, {})
        elif parsed.path == '/api/v1/export':
            actor = self._authorize_request(parsed.path, params, export=True)
            if actor is None:
                return
            filters = _request_filters(params)
            valid_export_window, export_error = self._validate_export_window(filters)
            if not valid_export_window:
                metrics.record_export_denied()
                self._record_api_audit(actor, "export", parsed.path, 403, filters, export_error)
                self._json_error(403, export_error or "invalid export window")
                return
            rows, source = self._search_records(filters, actor, min(self._limit_from_params(params, default=1000), API_EXPORT_MAX_ROWS))
            metrics.record_export_request()
            export_format = (params.get("format", ["json"])[0] or "json").lower()
            export_headers = {
                "X-AuditLens-Source": source,
                "X-AuditLens-Last-Enriched-At": api_state.snapshot().get("last_enriched_ingest_at") or "",
                "X-AuditLens-Partial-Data": "false" if source == "persistence" else "true",
            }
            if export_format == "csv":
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                self._send_bytes(200, "text/csv", self._serialize_export_csv(rows), headers=export_headers)
            elif export_format == "jsonl":
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                payload = "\n".join(orjson.dumps(row).decode("utf-8") for row in rows).encode("utf-8")
                self._send_bytes(200, "application/x-ndjson", payload, headers=export_headers)
            else:
                self._record_api_audit(actor, "export", parsed.path, 200, filters)
                self._send_json(200, {
                    "metadata": {
                        "partial_data": source != "persistence",
                        "freshness_timestamp": api_state.snapshot().get("last_enriched_ingest_at"),
                        "source": source,
                    },
                    "items": rows,
                    "count": len(rows),
                    "exported_at": utc_now_iso(),
                    "coverage_note": "export served from durable persistence" if source == "persistence" else api_state.snapshot()["coverage_note"],
                    "source": source,
                }, headers=export_headers)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = orjson.loads(raw_body) if raw_body else {}
        except orjson.JSONDecodeError:
            self._json_error(400, "invalid json body")
            return

        if parsed.path == "/api/v1/replay":
            actor = self._authorize_request(parsed.path, {}, export=False)
            if actor is None:
                return
            if actor.role != Role.ADMIN:
                self._record_api_audit(actor, "replay", parsed.path, 403, body, "admin access required")
                self._json_error(403, "admin access required")
                return
            if replay_state.snapshot()["in_progress"]:
                self._record_api_audit(actor, "replay", parsed.path, 409, body, "replay already in progress")
                self._json_error(409, "replay already in progress")
                return

            source_mode = body.get("source_mode", "raw")
            from_earliest = bool(body.get("from_earliest", False))
            hours = body.get("hours")
            if hours is not None:
                hours = int(hours)
            publish_topics = bool(body.get("publish_topics", REPLAY_PUBLISH_DERIVED_TOPICS))

            def _runner():
                try:
                    replay_events(
                        source_mode=source_mode,
                        hours=hours,
                        from_earliest=from_earliest,
                        publish_topics=publish_topics,
                    )
                except Exception:
                    logger.exception("Replay background operation failed")

            thread = threading.Thread(target=_runner, daemon=True, name="auditlens-replay")
            thread.start()
            self._record_api_audit(actor, "replay", parsed.path, 202, body)
            self._send_json(202, {
                "status": "accepted",
                "source_mode": source_mode,
                "from_earliest": from_earliest,
                "hours": hours,
                "publish_topics": publish_topics,
                "replay_state": replay_state.snapshot(),
            })
            return

        if parsed.path == "/admin/vacuum":
            actor = self._authorize_request(parsed.path, {}, export=False)
            if actor is None:
                return
            if actor.role != Role.ADMIN:
                self._record_api_audit(actor, "vacuum", parsed.path, 403, body, "admin access required")
                self._json_error(403, "admin access required")
                return
            if not (product_store and PERSISTENCE_CONFIG.enabled):
                self._record_api_audit(actor, "vacuum", parsed.path, 503, body, "persistence disabled")
                self._json_error(503, "persistence disabled")
                return
            try:
                result = product_store.vacuum()
            except Exception as exc:
                logger.exception("VACUUM via /admin/vacuum failed")
                self._record_api_audit(actor, "vacuum", parsed.path, 500, body, str(exc))
                self._json_error(500, f"vacuum failed: {exc}")
                return
            status_code = 200 if result.get("status") == "success" else 500
            self._record_api_audit(actor, "vacuum", parsed.path, status_code, body)
            self._send_json(status_code, result)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress HTTP server logs to avoid cluttering the output
        pass

class AuditLensHealthServer(HTTPServer):
    def handle_error(self, request, client_address):
        exc_type = sys.exc_info()[0]
        if exc_type in (BrokenPipeError, ConnectionResetError):
            return  # Normal client disconnect — suppress socketserver stderr output
        logger.debug(
            "Health server minor error from %s: %s",
            client_address, sys.exc_info()[1],
        )


def start_metrics_server(
    port=METRICS_PORT,
    *,
    metrics_obj,
    product_store_obj,
    api_state_obj,
    replay_state_obj,
    authenticator_obj,
    delivery_errors_dict,
    dlq_stats_dict,
    validate_startup_config_fn,
    replay_events_fn,
):
    """Start metrics/health server with injected runtime singletons."""
    global metrics, product_store, api_state, replay_state, authenticator
    global delivery_errors, dlq_stats, validate_startup_config, replay_events
    metrics = metrics_obj
    product_store = product_store_obj
    api_state = api_state_obj
    replay_state = replay_state_obj
    authenticator = authenticator_obj
    delivery_errors = delivery_errors_dict
    dlq_stats = dlq_stats_dict
    validate_startup_config = validate_startup_config_fn
    replay_events = replay_events_fn

    server = AuditLensHealthServer(('0.0.0.0', port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Metrics server started on port {port}")
    return server
