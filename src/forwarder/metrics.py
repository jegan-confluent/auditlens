"""In-process metrics tracker for the AuditLens forwarder."""

import threading
import time

from src.forwarder.config import PERSISTENCE_CONFIG, KAFKA_DEGRADED_AFTER_ERRORS
from src.forwarder.utils import utc_now_iso


# ──────────── metrics tracking ────────────
class Metrics:
    def __init__(self):
        self.start_time = time.time()
        self.processed_total = 0
        self.error_count = 0
        self.last_process_time = time.time()
        self.partition_lag = {}
        # Set by the consumer thread on every poll cycle so /health can show
        # whether the processor is keeping up with fetched batches.
        self.record_queue_depth = 0
        self.record_queue_capacity = 0
        # Priority-queue depths (between processor and async DB writers).
        # Updated by writer threads + by the processor on enqueue. Surfaced
        # via /health so operators can see which lane is backing up.
        self.critical_queue_depth = 0
        self.normal_queue_depth = 0
        self.bulk_queue_depth = 0
        self.catalog_queue_depth = 0
        # Count of events the consumer thread routed straight to the bulk
        # writer without entering the processor. Useful to confirm the
        # short-circuit is firing in production. Incremented atomically
        # under self.lock by record_noise_short_circuited().
        self.noise_short_circuited_total = 0
        self.dry_run_suppressed_total = 0
        # Count of batches where the bulk writer didn't persist all
        # short-circuited noise offsets in time (we did NOT commit;
        # restart will replay). High value signals bulk lane backpressure.
        self.noise_persist_wait_timeouts_total = 0
        # ── DB-writer freshness state for /health ─────────────────────
        # ISO-8601 UTC timestamp of the most-recent event time observed
        # in any successfully-written batch (signal or noise lane).
        # `db_behind_seconds` is computed off this — the gap between
        # wall-clock now and the latest event Postgres has actually seen.
        self.db_last_event_timestamp_iso: str | None = None
        # Consecutive write-error count: bumped on every record_db_write_error,
        # reset to 0 on every record_db_write_success. Distinct from
        # db_write_error_total (cumulative). The /health db_writer.status
        # classification uses this — a healthy lane means at least one
        # writer just succeeded.
        self.db_write_consecutive_error_count = 0
        self.last_ingested_event_time = None
        self.last_committed_at = None
        self.offset_commits_total = 0
        self.offset_commit_failures_total = 0
        self.rebalance_count = 0
        self.restart_count = 0
        self.parse_error_count = 0
        self.persistence_write_failures = 0
        self.persistence_write_success_total = 0
        self.api_auth_failures_total = 0
        self.export_requests_total = 0
        self.export_denied_total = 0
        self.replay_runs_total = 0
        self.replay_failures_total = 0
        self.replay_in_progress = False
        self.replay_last_started_at = None
        self.replay_last_completed_at = None
        self.replay_last_success_at = None
        self.replay_last_error = None
        self.replay_records_processed_total = 0
        self.replay_source_mode = None
        self.replay_window = None
        self.poll_count = 0
        self.empty_poll_count = 0
        self.records_consumed_total = 0
        self.retry_count = 0
        self.consecutive_error_count = 0
        self.last_error = None
        self.last_error_at = None
        self.last_successful_poll = None
        self.backoff_seconds = 0.0
        self.consumer_state = "starting"
        self.db_write_success_total = 0
        self.db_write_error_total = 0
        self.db_write_batch_size = 0
        self.db_last_successful_write = None
        self.db_writer_state = "disabled"
        self.db_last_error = None
        self.db_last_cleanup_at = None
        self.db_last_cleanup_deleted_count = 0
        self.produce_retry_exhausted_total = 0
        self.delivery_attempts_by_topic = {}
        self.delivery_success_by_topic = {}
        self.delivery_failures_by_topic = {}
        self.signal_counts = {}
        self.data_quality = {
            "missing_principal_total": 0,
            "missing_resource_total": 0,
            "unknown_method_total": 0,
            "classification_fallback_total": 0,
            "suppressed_authz_noise_total": 0,
        }
        self.persistence_status = {
            "enabled": PERSISTENCE_CONFIG.enabled,
            "healthy": False,
            "backend": PERSISTENCE_CONFIG.backend,
            "last_write_at": None,
            "db_path": PERSISTENCE_CONFIG.db_path,
            "db_file_bytes": 0,
            "wal_file_bytes": 0,
            "current_db_size": 0,
            "max_db_size": PERSISTENCE_CONFIG.db_max_bytes,
            "free_disk_bytes": 0,
            "db_max_bytes": PERSISTENCE_CONFIG.db_max_bytes,
            "wal_max_bytes": PERSISTENCE_CONFIG.wal_max_bytes,
            "storage_mode": "normal",
            "free_disk_warning_bytes": PERSISTENCE_CONFIG.free_disk_warning_bytes,
            "free_disk_critical_bytes": PERSISTENCE_CONFIG.free_disk_critical_bytes,
            "storage_status": "ok",
            "storage_reasons": [],
            "data_retention_mode": "bounded_hot_cache",
            "hot_cache_retention_hours": PERSISTENCE_CONFIG.rotation_retention_hours,
            "archive_enabled": False,
            "data_loss_possible": True,
            "write_guard_active": False,
            "storage_degraded": False,
            "last_cleanup_at": None,
            "last_cleanup_deleted_rows": 0,
            "last_cleanup_time_deleted_rows": 0,
            "last_cleanup_size_deleted_rows": 0,
            "last_cleanup_strategy": "none",
            "cleanup_status": "not_run",
            "cleanup_last_error": None,
            "size_cleanup_status": "not_run",
            "size_cleanup_last_error": None,
            "size_cleanup_pressure_bytes": 0,
            "size_cleanup_target_bytes": int(PERSISTENCE_CONFIG.db_max_bytes * PERSISTENCE_CONFIG.adaptive_retention_target_ratio),
            "sqlite_page_size": 0,
            "sqlite_freelist_pages": 0,
            "sqlite_reclaimable_bytes": 0,
            "last_vacuum_at": None,
            "last_vacuum_status": "not_run",
            "last_vacuum_error": None,
            "rotation_in_progress": False,
            "last_rotation_time": None,
            "rows_copied": 0,
            "rotation_duration_ms": 0,
            "rotation_total": 0,
            "rotation_status": "not_run",
            "rotation_last_error": None,
            "rotation_trigger": None,
            "last_rotation_failure_time": None,
            "storage_write_dropped_total": 0,
            "adaptive_retention_min_hours": PERSISTENCE_CONFIG.adaptive_retention_min_hours,
            "adaptive_retention_max_batches": PERSISTENCE_CONFIG.adaptive_retention_max_batches,
            "size_cleanup_complete": True,
            "effective_retention_hours": {
                "enriched_events": PERSISTENCE_CONFIG.enriched_retention_days * 24,
                "high_risk_events": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "denial_summaries": PERSISTENCE_CONFIG.signals_retention_days * 24,
                "alerts": PERSISTENCE_CONFIG.alerts_retention_days * 24,
                "api_audit_log": PERSISTENCE_CONFIG.audit_retention_days * 24,
            },
            "last_checkpoint_at": None,
            "last_checkpoint_mode": None,
            "last_checkpoint_status": "not_run",
            "last_checkpoint_busy": 0,
            "last_checkpoint_log_frames": 0,
            "last_checkpoint_checkpointed_frames": 0,
            "last_checkpoint_error": None,
        }
        self.lock = threading.Lock()

    def record_processed(self, count, event_time=None):
        with self.lock:
            self.processed_total += count
            self.last_process_time = time.time()
            if event_time:
                self.last_ingested_event_time = event_time

    def record_poll(self, record_count: int = 0):
        with self.lock:
            self.poll_count += 1
            if record_count <= 0:
                self.empty_poll_count += 1
            else:
                self.records_consumed_total += record_count
                self.last_successful_poll = utc_now_iso()
                self.consecutive_error_count = 0
                self.backoff_seconds = 0.0
                self.consumer_state = "connected"

    def record_consumer_retry(self, error: str, backoff_seconds: float):
        with self.lock:
            self.retry_count += 1
            self.consecutive_error_count += 1
            self.error_count += 1
            self.last_error = error
            self.last_error_at = utc_now_iso()
            self.backoff_seconds = backoff_seconds
            self.consumer_state = (
                "degraded"
                if self.consecutive_error_count >= KAFKA_DEGRADED_AFTER_ERRORS
                else "backoff"
            )

    def set_consumer_state(self, state: str, backoff_seconds: float = 0.0):
        with self.lock:
            self.consumer_state = state
            self.backoff_seconds = backoff_seconds

    def record_noise_short_circuited(self, count: int = 1):
        with self.lock:
            self.noise_short_circuited_total += int(count)

    def record_dry_run_suppressed(self, count: int = 1):
        with self.lock:
            self.dry_run_suppressed_total += int(count)

    def record_noise_persist_wait_timeout(self):
        with self.lock:
            self.noise_persist_wait_timeouts_total += 1

    def record_db_write_success(
        self,
        batch_size: int,
        max_event_timestamp_iso: str | None = None,
    ):
        with self.lock:
            self.db_write_success_total += 1
            self.db_write_batch_size = batch_size
            self.db_last_successful_write = utc_now_iso()
            self.db_writer_state = "connected"
            self.db_last_error = None
            self.db_write_consecutive_error_count = 0
            # Advance the per-event-time freshness mark monotonically. ISO
            # strings compare correctly when both are UTC-Zulu — that's
            # the shape _max_event_timestamp_iso emits.
            if max_event_timestamp_iso:
                current = self.db_last_event_timestamp_iso
                if current is None or max_event_timestamp_iso > current:
                    self.db_last_event_timestamp_iso = max_event_timestamp_iso

    def record_db_write_error(self, error: str, batch_size: int = 0):
        with self.lock:
            self.db_write_error_total += 1
            self.db_write_consecutive_error_count += 1
            self.error_count += 1
            self.db_write_batch_size = batch_size
            self.db_writer_state = "degraded"
            self.db_last_error = error

    def record_db_retention_cleanup(self, cleanup: dict):
        with self.lock:
            self.db_last_cleanup_at = cleanup.get("last_cleanup_at")
            self.db_last_cleanup_deleted_count = int(cleanup.get("deleted_count") or 0)

    def set_db_writer_state(self, state: str):
        with self.lock:
            self.db_writer_state = state

    def record_error(self):
        with self.lock:
            self.error_count += 1

    def record_parse_error(self):
        with self.lock:
            self.parse_error_count += 1
            self.error_count += 1

    def record_commit_success(self):
        with self.lock:
            self.offset_commits_total += 1
            self.last_committed_at = utc_now_iso()

    def record_commit_failure(self):
        with self.lock:
            self.offset_commit_failures_total += 1
            self.error_count += 1

    def record_rebalance(self):
        with self.lock:
            self.rebalance_count += 1

    def set_restart_count(self, count: int):
        with self.lock:
            self.restart_count = count

    def record_persistence_success(self, status: dict):
        with self.lock:
            self.persistence_write_success_total += 1
            self.persistence_status.update(status)

    def record_persistence_failure(self, error: str):
        with self.lock:
            self.persistence_write_failures += 1
            self.error_count += 1
            self.persistence_status["healthy"] = False
            self.persistence_status["last_error"] = error

    def record_delivery_attempt(self, topic: str):
        with self.lock:
            self.delivery_attempts_by_topic[topic] = self.delivery_attempts_by_topic.get(topic, 0) + 1

    def record_delivery_success(self, topic: str):
        with self.lock:
            self.delivery_success_by_topic[topic] = self.delivery_success_by_topic.get(topic, 0) + 1

    def record_delivery_failure(self, topic: str):
        with self.lock:
            self.delivery_failures_by_topic[topic] = self.delivery_failures_by_topic.get(topic, 0) + 1

    def record_produce_retry_exhausted(self):
        with self.lock:
            self.produce_retry_exhausted_total += 1

    def record_signal(self, signal_type: str):
        with self.lock:
            self.signal_counts[signal_type] = self.signal_counts.get(signal_type, 0) + 1

    def record_api_auth_failure(self):
        with self.lock:
            self.api_auth_failures_total += 1

    def record_export_request(self):
        with self.lock:
            self.export_requests_total += 1

    def record_export_denied(self):
        with self.lock:
            self.export_denied_total += 1

    def replay_started(self, source_mode: str, window: str):
        with self.lock:
            self.replay_runs_total += 1
            self.replay_in_progress = True
            self.replay_last_started_at = utc_now_iso()
            self.replay_source_mode = source_mode
            self.replay_window = window
            self.replay_last_error = None

    def replay_progress(self, processed_delta: int = 0):
        with self.lock:
            self.replay_records_processed_total += processed_delta

    def replay_finished(self, success: bool, error: str | None = None):
        with self.lock:
            self.replay_in_progress = False
            self.replay_last_completed_at = utc_now_iso()
            self.replay_last_error = error
            if success:
                self.replay_last_success_at = self.replay_last_completed_at
            else:
                self.replay_failures_total += 1

    def record_data_quality(self, flat: dict, classification_result):
        with self.lock:
            if not flat.get("principal_normalized"):
                self.data_quality["missing_principal_total"] += 1
            if not (flat.get("resourceName") or flat.get("authzResourceName")):
                self.data_quality["missing_resource_total"] += 1
            if classification_result.method_category == "unknown":
                self.data_quality["unknown_method_total"] += 1
            if str(classification_result.reason).startswith("Unclassified method"):
                self.data_quality["classification_fallback_total"] += 1
            method = flat.get("methodName") or ""
            if method.endswith(".Authorize") and flat.get("granted") is True:
                self.data_quality["suppressed_authz_noise_total"] += 1
            if flat.get("validateOnly"):
                self.dry_run_suppressed_total += 1

    def update_lag(self, partition, position, high):
        with self.lock:
            self.partition_lag[partition] = high - position

    def get_metrics(self):
        with self.lock:
            uptime = time.time() - self.start_time
            idle_time = time.time() - self.last_process_time
            total_lag = sum(self.partition_lag.values()) if self.partition_lag else 0

            return {
                "uptime_seconds": uptime,
                "processed_messages_total": self.processed_total,
                "processing_rate_per_second": self.processed_total / uptime if uptime > 0 else 0,
                "error_count": self.error_count,
                "idle_seconds": idle_time,
                "consumer_lag_total": total_lag,
                "consumer_lag_by_partition": self.partition_lag,
                "record_queue_depth": int(self.record_queue_depth),
                "record_queue_capacity": int(self.record_queue_capacity),
                "priority_queue_depths": {
                    "critical": int(self.critical_queue_depth),
                    "normal": int(self.normal_queue_depth),
                    "bulk": int(self.bulk_queue_depth),
                    "catalog": int(self.catalog_queue_depth),
                },
                "noise_short_circuited_total": int(self.noise_short_circuited_total),
                "noise_persist_wait_timeouts_total": int(self.noise_persist_wait_timeouts_total),
                "dry_run_suppressed_total": int(self.dry_run_suppressed_total),
                "last_ingested_event_time": self.last_ingested_event_time,
                "last_committed_at": self.last_committed_at,
                "offset_commits_total": self.offset_commits_total,
                "offset_commit_failures_total": self.offset_commit_failures_total,
                "rebalance_count": self.rebalance_count,
                "restart_count": self.restart_count,
                "parse_error_count": self.parse_error_count,
                "persistence_write_failures": self.persistence_write_failures,
                "persistence_write_success_total": self.persistence_write_success_total,
                "api_auth_failures_total": self.api_auth_failures_total,
                "export_requests_total": self.export_requests_total,
                "export_denied_total": self.export_denied_total,
                "replay_runs_total": self.replay_runs_total,
                "replay_failures_total": self.replay_failures_total,
                "replay_in_progress": self.replay_in_progress,
                "replay_last_started_at": self.replay_last_started_at,
                "replay_last_completed_at": self.replay_last_completed_at,
                "replay_last_success_at": self.replay_last_success_at,
                "replay_last_error": self.replay_last_error,
                "replay_records_processed_total": self.replay_records_processed_total,
                "replay_source_mode": self.replay_source_mode,
                "replay_window": self.replay_window,
                "poll_count": self.poll_count,
                "empty_poll_count": self.empty_poll_count,
                "records_consumed_total": self.records_consumed_total,
                "retry_count": self.retry_count,
                "consecutive_error_count": self.consecutive_error_count,
                "last_error": self.last_error,
                "last_error_at": self.last_error_at,
                "last_successful_poll": self.last_successful_poll,
                "backoff_seconds": self.backoff_seconds,
                "consumer_state": self.consumer_state,
                "db_write_success_total": self.db_write_success_total,
                "db_write_error_total": self.db_write_error_total,
                "db_write_consecutive_error_count": self.db_write_consecutive_error_count,
                "db_write_batch_size": self.db_write_batch_size,
                "db_last_successful_write": self.db_last_successful_write,
                "db_last_event_timestamp_iso": self.db_last_event_timestamp_iso,
                "db_writer_state": self.db_writer_state,
                "db_last_error": self.db_last_error,
                "db_last_cleanup_at": self.db_last_cleanup_at,
                "db_last_cleanup_deleted_count": self.db_last_cleanup_deleted_count,
                "produce_retry_exhausted_total": self.produce_retry_exhausted_total,
                "delivery_attempts_by_topic": dict(self.delivery_attempts_by_topic),
                "delivery_success_by_topic": dict(self.delivery_success_by_topic),
                "delivery_failures_by_topic": dict(self.delivery_failures_by_topic),
                "signal_counts": dict(self.signal_counts),
                "data_quality": dict(self.data_quality),
                "persistence_status": dict(self.persistence_status),
            }
