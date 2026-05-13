"""Productization tests for auth, persistence, RBAC, exports, and recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import orjson
import audit_forwarder as forwarder
import src.product.db_writer as db_writer_module
from src.product.auth import AccessToken, AuthConfig, Authenticator, Role
from src.product.db_writer import AuditEventDbWriter, DbWriteResult
from src.product.event_normalization import event_fingerprint
from src.product.persistence import PersistenceConfig, SQLiteProductStore


def _store(tmp_path: Path) -> SQLiteProductStore:
    store = SQLiteProductStore(PersistenceConfig(db_path=str(tmp_path / "auditlens.db")))
    store.initialize()
    return store


def _actor(role: Role, organizations=("*",), environments=("*",), clusters=("*",)):
    return AccessToken(
        token="token",
        actor_id=f"{role.value}-actor",
        role=role,
        organizations=organizations,
        environments=environments,
        clusters=clusters,
    )


def test_restart_before_commit_blocks_offset_commit():
    should_commit, details = forwarder.evaluate_batch_commit(
        flush_remaining=0,
        delivery_errors_before=0,
        delivery_errors_after=0,
        processing_failed=True,
    )
    assert should_commit is False
    assert details["processing_failed"] is True


def test_restart_after_commit_allows_offset_commit():
    should_commit, _ = forwarder.evaluate_batch_commit(
        flush_remaining=0,
        delivery_errors_before=0,
        delivery_errors_after=0,
        processing_failed=False,
    )
    assert should_commit is True


def test_duplicate_replay_tolerance_uses_upsert(tmp_path):
    store = _store(tmp_path)
    event = {
        "id": "evt-1",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-1",
        "environment_id": "env-1",
        "cluster_id": "lkc-1",
        "principal_raw": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-1",
        "criticality": "CRITICAL",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 101)
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 101)

    rows = store.query_enriched({}, _actor(Role.ADMIN), 10)
    assert len(rows) == 1


def test_forwarder_db_writer_batch_insert_deduplicates_and_normalizes(tmp_path):
    writer = AuditEventDbWriter(f"sqlite:///{tmp_path / 'auditlens_api.db'}")
    event = {
        "id": "evt-db-1",
        "time": "2026-04-19T10:00:00Z",
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-75rw9o",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=jegan-testing",
        "summary": "u-75rw9o created topic 'jegan-testing'",
        "resultStatus": "Success",
    }

    first = writer.write_batch([event])
    replay = writer.write_batch([event])
    health = writer.health()

    assert first.inserted == 1
    assert replay.inserted == 0
    assert health["event_count"] == 1
    with writer.engine.connect() as conn:
        row = conn.exec_driver_sql(
            "select normalized_action, action_category, resource_type, resource_name, is_failure, is_denied from audit_events"
        ).mappings().one()
    assert row["normalized_action"] == "Create topic"
    assert row["action_category"] == "Create"
    assert row["resource_type"] == "topic"
    assert row["resource_name"] == "jegan-testing"
    assert row["is_failure"] in (False, 0)
    assert row["is_denied"] in (False, 0)


def test_forwarder_db_writer_resource_catalog_failure_is_best_effort(tmp_path, monkeypatch):
    writer = AuditEventDbWriter(f"sqlite:///{tmp_path / 'auditlens_api.db'}")
    event = {
        "id": "evt-db-best-effort",
        "time": "2026-04-19T10:00:00Z",
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-75rw9o",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=jegan-testing",
        "summary": "u-75rw9o created topic 'jegan-testing'",
        "resultStatus": "Success",
    }

    def failing_build(*args, **kwargs):
        raise RuntimeError("catalog down")

    monkeypatch.setattr(db_writer_module, "build_resource_catalog_entry", failing_build)
    result = writer.write_batch([event])

    assert result.attempted == 1
    assert result.inserted == 1
    with writer.engine.connect() as conn:
        count = conn.exec_driver_sql("select count(*) from audit_events").scalar_one()
        catalog_count = conn.exec_driver_sql("select count(*) from resource_catalog").scalar_one()
    assert count == 1
    assert catalog_count == 0


def test_fingerprint_for_timestamp_missing_event_is_stable():
    event = {
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-75rw9o",
        "cluster_id": "lkc-demo",
        "resourceName": "crn://confluent.cloud/topic=jegan-testing",
        "summary": "u-75rw9o created topic 'jegan-testing'",
        "source_topic": "confluent-audit-log-events",
        "source_partition": 0,
        "source_offset": 42,
    }

    assert event_fingerprint(event) == event_fingerprint(dict(event))


def test_fingerprint_management_plane_deduplicates_double_emit():
    # Two events representing the same IAM operation (same actor, action,
    # resource, timestamp-second) but different message IDs (Confluent
    # double-emit). They must produce the same fingerprint.
    base = {
        "methodName": "CreateAPIKey",
        "user": "u-12g806",
        "resourceName": "76NATGA2SWTNEZX5",
        "time": "2026-05-04T13:06:37.100000Z",
    }
    emit1 = {**base, "id": "msg-id-aaa", "source_offset": 101}
    emit2 = {**base, "id": "msg-id-bbb", "source_offset": 102}
    assert event_fingerprint(emit1) == event_fingerprint(emit2)


def test_fingerprint_kafka_data_plane_uses_unique_id():
    # Kafka data-plane events (kafka. prefix) use the message ID so two
    # different Produce calls with the same payload are not collapsed.
    base = {
        "methodName": "kafka.Produce",
        "user": "sa-abc",
        "resourceName": "crn://confluent.cloud/topic=orders",
        "time": "2026-05-04T13:06:37.100000Z",
    }
    emit1 = {**base, "id": "msg-id-aaa"}
    emit2 = {**base, "id": "msg-id-bbb"}
    assert event_fingerprint(emit1) != event_fingerprint(emit2)


def test_forwarder_db_writer_retention_cleanup_deletes_old_rows(tmp_path):
    writer = AuditEventDbWriter(f"sqlite:///{tmp_path / 'auditlens_api.db'}", retention_days=7)
    old_event = {
        "id": "evt-old",
        "time": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        "methodName": "kafka.DeleteTopics",
        "action": "DeleteTopics",
        "user": "u-old",
        "resourceName": "crn://confluent.cloud/topic=old-topic",
    }
    fresh_event = {
        "id": "evt-fresh",
        "time": datetime.now(timezone.utc).isoformat(),
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-new",
        "resourceName": "crn://confluent.cloud/topic=fresh-topic",
    }

    writer.write_batch([old_event, fresh_event])
    dry_run = writer.cleanup_retention(dry_run=True)
    cleanup = writer.cleanup_retention(dry_run=False)

    assert dry_run["deleted_count"] == 1
    assert cleanup["deleted_count"] == 1
    assert writer.health()["event_count"] == 1
    assert writer.health()["last_cleanup_deleted_count"] == 1


def test_forwarder_db_backoff_and_recovery_updates_metrics(monkeypatch):
    class FailingWriter:
        def write_batch(self, payloads):
            raise ConnectionError("db unavailable")

    class RecoveringWriter:
        def write_batch(self, payloads):
            return DbWriteResult(attempted=len(payloads), inserted=len(payloads), elapsed_ms=1.0)

        def cleanup_retention_if_due(self):
            return {"last_cleanup_at": "2026-04-28T00:00:00+00:00", "deleted_count": 2}

    monkeypatch.setattr(forwarder, "ENABLE_DB_WRITER", True)
    monkeypatch.setattr(forwarder, "metrics", forwarder.Metrics())
    monkeypatch.setattr(forwarder, "_sleep_with_shutdown", lambda delay: None)

    monkeypatch.setattr(forwarder, "db_writer", FailingWriter())
    failed = forwarder.flush_db_writer_batch([{"id": "evt-fail"}], forwarder.RuntimeBackoff(initial=0.1, maximum=0.1, jitter_ratio=0), {})
    assert failed is False
    assert forwarder.metrics.get_metrics()["db_writer_state"] == "backoff"
    assert forwarder.metrics.get_metrics()["db_write_error_total"] == 1

    monkeypatch.setattr(forwarder, "db_writer", RecoveringWriter())
    recovered = forwarder.flush_db_writer_batch([{"id": "evt-ok"}], forwarder.RuntimeBackoff(initial=0.1, maximum=0.1, jitter_ratio=0), {})
    metrics = forwarder.metrics.get_metrics()
    assert recovered is True
    assert metrics["db_writer_state"] == "connected"
    assert metrics["db_write_success_total"] == 1
    assert metrics["db_last_cleanup_at"] == "2026-04-28T00:00:00+00:00"
    assert metrics["db_last_cleanup_deleted_count"] == 2


def test_persistence_health_exposes_storage_and_checkpoint_status(tmp_path):
    store = _store(tmp_path)
    event = {
        "id": "evt-storage",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-1",
        "environment_id": "env-1",
        "cluster_id": "lkc-1",
        "principal_raw": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-1",
        "criticality": "CRITICAL",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 101)
    store.cleanup_expired()
    checkpoint = store.checkpoint_wal()

    health = store.health()

    assert health["db_file_bytes"] > 0
    assert health["free_disk_bytes"] > 0
    assert health["db_max_bytes"] > 0
    assert health["storage_status"] in {"ok", "warning", "critical"}
    assert health["last_cleanup_at"] is not None
    assert health["cleanup_status"] == "success"
    assert health["last_checkpoint_at"] is not None
    assert health["last_checkpoint_status"] == "success"
    assert checkpoint["status"] == "success"
    assert health["data_retention_mode"] == "bounded_hot_cache"
    assert health["hot_cache_retention_hours"] == store.config.rotation_retention_hours
    assert health["archive_enabled"] is False
    assert health["data_loss_possible"] is True
    assert "write_guard_active" in health
    assert "storage_degraded" in health
    assert "rotation_trigger" in health
    assert "last_rotation_failure_time" in health


def test_size_pressure_cleanup_adapts_retention_without_deleting_hot_rows(tmp_path):
    store = SQLiteProductStore(
        PersistenceConfig(
            db_path=str(tmp_path / "auditlens.db"),
            enriched_retention_days=30,
            db_max_bytes=1_000_000,
            adaptive_retention_min_hours=1,
            adaptive_retention_target_ratio=0.10,
            adaptive_retention_batch_rows=5,
            adaptive_retention_max_batches=100,
        )
    )
    store.initialize()
    old_time = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat().replace("+00:00", "Z")
    hot_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    large_payload = "x" * 5000

    for index in range(20):
        store.persist_enriched_event(
            {
                "id": f"evt-old-{index}",
                "time": old_time,
                "organization_id": "org-1",
                "environment_id": "env-1",
                "cluster_id": "lkc-1",
                "principal_raw": "User:old",
                "principal_normalized": "old",
                "principal_type": "service_account",
                "methodName": "kafka.CreateAcls",
                "resourceName": "topic-old",
                "criticality": "LOW",
                "large_payload": large_payload,
            },
            "audit.enriched.v1",
            0,
            index,
        )
    store.persist_enriched_event(
        {
            "id": "evt-hot",
            "time": hot_time,
            "organization_id": "org-1",
            "environment_id": "env-1",
            "cluster_id": "lkc-1",
            "principal_raw": "User:hot",
            "principal_normalized": "hot",
            "principal_type": "service_account",
            "methodName": "kafka.CreateAcls",
            "resourceName": "topic-hot",
            "criticality": "LOW",
        },
        "audit.enriched.v1",
        0,
        99,
    )

    deleted_rows = store.cleanup_expired()
    health = store.health()
    old_rows = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id LIKE 'evt-old-%'").fetchone()
    hot_rows = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id = 'evt-hot'").fetchone()

    assert deleted_rows > 0
    assert old_rows["count"] == 0
    assert hot_rows["count"] == 1
    assert health["last_cleanup_strategy"] == "time_retention+size_pressure"
    assert health["last_cleanup_size_deleted_rows"] > 0
    assert health["size_cleanup_status"] in {"success", "partial"}
    assert health["effective_retention_hours"]["enriched_events"] < 30 * 24


def test_storage_mode_threshold_transitions(tmp_path, monkeypatch):
    store = SQLiteProductStore(PersistenceConfig(db_path=str(tmp_path / "auditlens.db"), db_max_bytes=1000))
    store.initialize()

    monkeypatch.setattr(store, "_storage_bytes", lambda: 799)
    assert store._storage_mode() == "normal"
    monkeypatch.setattr(store, "_storage_bytes", lambda: 800)
    assert store._storage_mode() == "warning"
    monkeypatch.setattr(store, "_storage_bytes", lambda: 900)
    assert store._storage_mode() == "critical"
    monkeypatch.setattr(store, "_storage_bytes", lambda: 950)
    assert store._storage_mode() == "emergency"


def test_rotation_triggers_and_keeps_recent_data(tmp_path):
    store = SQLiteProductStore(
        PersistenceConfig(
            db_path=str(tmp_path / "auditlens.db"),
            db_max_bytes=10_000_000,
            rotation_retention_hours=6,
            rotation_target_ratio=0.80,
            rotation_copy_batch_rows=10,
            adaptive_retention_batch_rows=10,
            adaptive_retention_max_batches=5,
        )
    )
    store.initialize()
    old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    large_payload = "x" * 20_000
    for index in range(50):
        store.persist_enriched_event(
            {
                "id": f"evt-rotate-old-{index}",
                "time": old_time,
                "organization_id": "org-1",
                "environment_id": "env-1",
                "cluster_id": "lkc-1",
                "principal_normalized": "old",
                "methodName": "kafka.CreateAcls",
                "resourceName": "topic-old",
                "criticality": "LOW",
                "large_payload": large_payload,
            },
            "audit.enriched.v1",
            0,
            index,
        )
    for index in range(3):
        store.persist_enriched_event(
            {
                "id": f"evt-rotate-recent-{index}",
                "time": recent_time,
                "organization_id": "org-1",
                "environment_id": "env-1",
                "cluster_id": "lkc-1",
                "principal_normalized": "recent",
                "methodName": "kafka.CreateAcls",
                "resourceName": "topic-recent",
                "criticality": "LOW",
            },
            "audit.enriched.v1",
            0,
            100 + index,
        )

    before_size = store.health()["current_db_size"]
    object.__setattr__(store.config, "db_max_bytes", max(100_000, before_size // 3))
    store.cleanup_expired()
    health = store.health()
    old_rows = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id LIKE 'evt-rotate-old-%'").fetchone()
    recent_rows = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id LIKE 'evt-rotate-recent-%'").fetchone()

    assert health["rotation_total"] == 1
    assert health["rows_copied"] >= 3
    assert health["current_db_size"] < before_size
    assert health["current_db_size"] <= health["max_db_size"]
    assert old_rows["count"] == 0
    assert recent_rows["count"] == 3


def test_emergency_mode_drops_low_priority_writes(tmp_path, monkeypatch):
    store = SQLiteProductStore(PersistenceConfig(db_path=str(tmp_path / "auditlens.db"), db_max_bytes=1000))
    store.initialize()
    monkeypatch.setattr(store, "_storage_bytes", lambda: 1000)

    store.persist_enriched_event(
        {
            "id": "evt-drop-low",
            "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "criticality": "LOW",
        },
        "audit.enriched.v1",
        0,
        1,
    )

    rows = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id = 'evt-drop-low'").fetchone()
    assert rows["count"] == 0
    assert store.health()["storage_write_dropped_total"] == 1


def test_storage_bound_enforcement_records_startup_trigger(tmp_path):
    store = SQLiteProductStore(
        PersistenceConfig(
            db_path=str(tmp_path / "auditlens.db"),
            db_max_bytes=10_000_000,
            rotation_retention_hours=6,
            rotation_copy_batch_rows=10,
        )
    )
    store.initialize()
    recent_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    old_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    large_payload = "x" * 20_000
    for index in range(30):
        store.persist_enriched_event(
            {
                "id": f"evt-startup-rotate-{index}",
                "time": old_time,
                "criticality": "LOW",
                "large_payload": large_payload,
            },
            "audit.enriched.v1",
            0,
            index,
        )
    for index in range(3):
        store.persist_enriched_event(
            {
                "id": f"evt-startup-recent-{index}",
                "time": recent_time,
                "criticality": "HIGH",
            },
            "audit.enriched.v1",
            0,
            100 + index,
        )

    before_size = store.health()["current_db_size"]
    object.__setattr__(store.config, "db_max_bytes", max(100_000, before_size // 3))
    health = store.enforce_storage_bounds(trigger="startup")

    assert health["rotation_total"] == 1
    assert health["rotation_trigger"] == "startup"
    assert health["rotation_status"] == "success"
    assert health["current_db_size"] <= health["max_db_size"]


def test_rotation_failure_sets_degraded_state(tmp_path, monkeypatch):
    store = SQLiteProductStore(PersistenceConfig(db_path=str(tmp_path / "auditlens.db"), db_max_bytes=1000))
    store.initialize()
    monkeypatch.setattr(store, "_storage_bytes", lambda: 1001)

    def fail_rotation(trigger="manual"):
        raise RuntimeError("simulated rotation failure")

    monkeypatch.setattr(store, "_rotate_hot_cache_unlocked", fail_rotation)
    health = store.enforce_storage_bounds(trigger="periodic")

    assert health["rotation_status"] == "failure"
    assert health["rotation_last_error"] == "simulated rotation failure"
    assert health["rotation_trigger"] == "periodic"
    assert health["last_rotation_failure_time"] is not None
    assert health["storage_degraded"] is True
    assert health["data_loss_possible"] is True
    assert health["write_guard_active"] is True
    assert health["storage_mode"] == "emergency"


def test_degraded_storage_drops_low_priority_but_preserves_high_priority(tmp_path, monkeypatch):
    store = SQLiteProductStore(PersistenceConfig(db_path=str(tmp_path / "auditlens.db"), db_max_bytes=1000))
    store.initialize()
    store._status["storage_degraded"] = True
    store._status["write_guard_active"] = True
    monkeypatch.setattr(store, "_storage_bytes", lambda: 999)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    store.persist_enriched_event({"id": "evt-degraded-low", "time": now, "criticality": "LOW"}, "audit.enriched.v1", 0, 1)
    store.persist_enriched_event({"id": "evt-degraded-high", "time": now, "criticality": "HIGH"}, "audit.enriched.v1", 0, 2)

    low = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id = 'evt-degraded-low'").fetchone()
    high = store._conn.execute("SELECT COUNT(*) AS count FROM enriched_events WHERE event_id = 'evt-degraded-high'").fetchone()

    assert low["count"] == 0
    assert high["count"] == 1
    assert store.health()["storage_write_dropped_total"] == 1


def test_periodic_storage_monitor_triggers_enforcement(monkeypatch):
    calls = []

    class FakeStore:
        def enforce_storage_bounds(self, trigger):
            calls.append(("enforce", trigger))
            return {
                "storage_mode": "warning",
                "storage_degraded": False,
                "current_db_size": 90,
                "max_db_size": 100,
                "write_guard_active": False,
            }

        def checkpoint_wal(self, mode):
            calls.append(("checkpoint", mode))

        def health(self):
            return {"healthy": True, "storage_mode": "warning"}

    monkeypatch.setattr(forwarder, "product_store", FakeStore())
    forwarder.run_storage_monitor_tick(trigger="periodic")

    assert ("enforce", "periodic") in calls
    assert ("checkpoint", "PASSIVE") in calls


def test_enriched_event_persisted(tmp_path):
    store = _store(tmp_path)
    event = {
        "id": "evt-enriched",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-1",
        "environment_id": "env-1",
        "cluster_id": "lkc-1",
        "principal_raw": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "methodName": "kafka.CreateAcls",
        "resourceName": "topic-a",
        "criticality": "HIGH",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 10)

    rows = store.query_enriched({"principal": "sa-1"}, _actor(Role.ADMIN), 10)
    assert rows[0]["id"] == "evt-enriched"
    assert rows[0]["_auditlens_source"]["offset"] == 10


def test_denial_summary_persisted(tmp_path):
    store = _store(tmp_path)
    summary = {
        "id": "denial-1",
        "time": "2026-04-19T10:05:00Z",
        "window_end": "2026-04-19T10:05:00Z",
        "organization_ids": ["org-1"],
        "environment_ids": ["env-1"],
        "cluster_ids": ["lkc-1"],
        "principal_normalized": "sa-1",
        "methodName": "mds.Authorize",
        "resource_name": "topic-a",
        "denial_count": 12,
    }
    store.persist_denial_summary(summary)

    rows = store.query_denials(_actor(Role.ADMIN), 10)
    assert rows[0]["id"] == "denial-1"


def test_api_search_can_return_persisted_results(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(forwarder, "product_store", store)
    event = {
        "id": "evt-search",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-1",
        "environment_id": "env-1",
        "cluster_id": "lkc-1",
        "principal_raw": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-1",
        "criticality": "CRITICAL",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 20)

    rows, source = forwarder.MetricsHandler._search_records(None, {"principal": "sa-1"}, _actor(Role.ADMIN), 10)
    assert source == "persistence"
    assert rows[0]["id"] == "evt-search"


def test_export_works_from_persisted_records(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(forwarder, "product_store", store)
    event = {
        "id": "evt-export",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-1",
        "environment_id": "env-1",
        "cluster_id": "lkc-1",
        "principal_raw": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-1",
        "criticality": "CRITICAL",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 21)
    rows, _ = forwarder.MetricsHandler._search_records(None, {"principal": "sa-1"}, _actor(Role.EXPORTER), 10)
    csv_bytes = forwarder.MetricsHandler._serialize_export_csv(None, rows)
    assert b"evt-export" in csv_bytes


def test_unauthorized_request_denied():
    auth = Authenticator(AuthConfig(enabled=True, tokens={}))
    result = auth.authenticate({})
    assert result.ok is False
    assert result.status_code == 401


def test_authorized_request_allowed():
    actor = _actor(Role.VIEWER)
    auth = Authenticator(AuthConfig(enabled=True, tokens={"abc": actor}))
    result = auth.authenticate({"Authorization": "Bearer abc"})
    assert result.ok is True
    assert result.actor == actor


def test_viewer_cannot_export():
    actor = _actor(Role.VIEWER)
    auth = Authenticator(AuthConfig(enabled=True, tokens={"abc": actor}))
    result = auth.require_export(actor)
    assert result.ok is False
    assert result.status_code == 403


def test_exporter_can_export():
    actor = _actor(Role.EXPORTER)
    auth = Authenticator(AuthConfig(enabled=True, tokens={"abc": actor}))
    result = auth.require_export(actor)
    assert result.ok is True


def test_authenticator_handles_invalid_token_without_error():
    actor = _actor(Role.ADMIN)
    auth = Authenticator(AuthConfig(enabled=True, tokens={"abc": actor}))
    result = auth.authenticate({"Authorization": "Bearer nope"})
    assert result.ok is False
    assert result.status_code == 401


def test_authenticator_handles_malformed_token_type_without_error():
    actor = _actor(Role.ADMIN)
    auth = Authenticator(AuthConfig(enabled=True, tokens={"abc": actor}))
    auth._extract_token = lambda headers: 123  # type: ignore[method-assign]
    result = auth.authenticate({})
    assert result.ok is False
    assert result.status_code == 401


def test_safe_produce_exhausts_retries_and_records_metric(monkeypatch):
    attempts = {"count": 0}
    dlq_calls = []

    class FakeProducer:
        def poll(self, timeout):
            return None

        def produce(self, *args, **kwargs):
            attempts["count"] += 1
            raise BufferError("producer buffer full")

    monkeypatch.setattr(forwarder, "metrics", forwarder.Metrics())
    monkeypatch.setattr(forwarder, "ENABLE_DLQ", True)
    monkeypatch.setattr(forwarder, "DLQ_TOPIC", "audit.dlq.v1")
    monkeypatch.setattr(forwarder, "send_to_dlq", lambda *args, **kwargs: dlq_calls.append((args, kwargs)))

    result = forwarder.safe_produce(FakeProducer(), "audit.topic", b"evt-1", b"{}")

    assert result is False
    assert attempts["count"] == forwarder.MAX_PRODUCE_RETRIES
    assert forwarder.metrics.get_metrics()["produce_retry_exhausted_total"] == 1
    assert dlq_calls


def test_flush_db_writer_buffer_retains_payloads_on_failure(monkeypatch):
    calls = {"count": 0}

    class FakeWriter:
        def write_batch(self, payloads):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("db down")
            return DbWriteResult(attempted=len(payloads), inserted=len(payloads), elapsed_ms=1.0)

        def cleanup_retention_if_due(self):
            return None

    writer = FakeWriter()
    monkeypatch.setattr(forwarder, "ENABLE_DB_WRITER", True)
    monkeypatch.setattr(forwarder, "initialize_db_writer_if_enabled", lambda: writer)
    monkeypatch.setattr(forwarder, "_sleep_with_shutdown", lambda delay: None)

    payloads = [{"id": "evt-1"}, {"id": "evt-2"}]
    backoff = forwarder.RuntimeBackoff(initial=0.1, maximum=0.1, jitter_ratio=0)

    failed = forwarder.flush_db_writer_buffer(payloads, backoff, {}, force=True)
    assert failed is False
    assert payloads == [{"id": "evt-1"}, {"id": "evt-2"}]

    succeeded = forwarder.flush_db_writer_buffer(payloads, backoff, {}, force=True)
    assert succeeded is True
    assert payloads == []


def test_scope_is_enforced(tmp_path):
    store = _store(tmp_path)
    event = {
        "id": "evt-scope",
        "time": "2026-04-19T10:00:00Z",
        "organization_id": "org-2",
        "environment_id": "env-2",
        "cluster_id": "lkc-2",
        "principal_raw": "User:sa-2",
        "principal_normalized": "sa-2",
        "principal_type": "service_account",
        "methodName": "DeleteKafkaCluster",
        "resourceName": "lkc-2",
        "criticality": "CRITICAL",
    }
    store.persist_enriched_event(event, "audit.enriched.v1", 0, 30)

    rows = store.query_enriched({}, _actor(Role.VIEWER, organizations=("org-1",)), 10)
    assert rows == []


def test_export_activity_logged_with_filters(tmp_path):
    store = _store(tmp_path)
    store.record_api_audit(
        actor_id="exporter-1",
        role="exporter",
        action="export",
        endpoint="/api/v1/export",
        status_code=200,
        remote_addr="127.0.0.1",
        user_agent="pytest",
        filters={"principal": "sa-1", "time_from": "2026-04-19T00:00:00Z"},
    )
    row = store._conn.execute("SELECT * FROM api_audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["action"] == "export"
    assert "sa-1" in row["filters_json"]
    assert "time_from" in row["filters_json"]


def test_health_exposes_freshness_coverage_and_persistence(monkeypatch, tmp_path):
    store = _store(tmp_path)
    monkeypatch.setattr(forwarder, "product_store", store)
    monkeypatch.setattr(forwarder, "AUTH_CONFIG", AuthConfig(enabled=True, tokens={"abc": _actor(Role.ADMIN)}))
    monkeypatch.setattr(forwarder.metrics, "get_metrics", lambda: {
        "uptime_seconds": 100,
        "processed_messages_total": 5,
        "processing_rate_per_second": 1.2,
        "error_count": 0,
        "idle_seconds": 301,
        "consumer_lag_total": 3,
        "consumer_lag_by_partition": {"0": 3},
        "last_ingested_event_time": "2026-04-19T10:00:00Z",
        "last_committed_at": "2026-04-19T10:00:05Z",
        "offset_commits_total": 1,
        "offset_commit_failures_total": 0,
        "rebalance_count": 1,
        "restart_count": 1,
        "parse_error_count": 0,
        "persistence_write_failures": 0,
        "persistence_write_success_total": 1,
        "api_auth_failures_total": 0,
        "export_requests_total": 0,
        "export_denied_total": 0,
        "delivery_attempts_by_topic": {},
        "delivery_success_by_topic": {},
        "delivery_failures_by_topic": {},
        "signal_counts": {},
        "data_quality": {},
        "persistence_status": store.health() | {"healthy": True},
    })

    status_code, payload = forwarder.MetricsHandler._health_payload(None)
    assert status_code == 503
    assert "freshness" in payload
    assert "coverage" in payload
    assert "offset_recovery" in payload
    component_names = {component["name"] for component in payload["components"]}
    assert "persistence" in component_names
    assert "replay" in component_names
    assert payload["observability"]["persistence_storage"]["db_file_bytes"] >= 0
    assert payload["observability"]["persistence_storage"]["db_max_bytes"] > 0
    assert "storage_status" in payload["observability"]["persistence_storage"]
    assert "last_checkpoint_status" in payload["observability"]["persistence_storage"]


def test_recompute_enriched_event_reclassifies_existing_event():
    event = {
        "id": "evt-replay",
        "time": "2026-04-19T10:00:00Z",
        "methodName": "DeleteKafkaCluster",
        "principal": "User:sa-1",
        "principal_normalized": "sa-1",
        "principal_type": "service_account",
        "resourceName": "lkc-1",
        "criticality": "LOW",
    }
    rebuilt = forwarder.recompute_enriched_event(event)
    assert rebuilt["criticality"] == "CRITICAL"
    assert rebuilt["is_high_risk"] is True


def test_auth_config_rejects_empty_token():
    try:
        AuthConfig.from_json(orjson.dumps([{
            "token": " ",
            "actor_id": "bad",
            "role": "viewer",
        }]).decode("utf-8"))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "must not be empty" in str(exc)


def test_authenticator_refreshes_token_file(tmp_path):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(orjson.dumps([{
        "token": "old-token",
        "actor_id": "viewer-1",
        "role": "viewer",
    }]).decode("utf-8"))
    config = AuthConfig.from_json(token_file.read_text(), token_file=str(token_file), token_file_mtime=token_file.stat().st_mtime)
    auth = Authenticator(config)
    assert auth.authenticate({"Authorization": "Bearer old-token"}).ok is True

    token_file.write_text(orjson.dumps([{
        "token": "new-token",
        "actor_id": "viewer-2",
        "role": "viewer",
    }]).decode("utf-8"))
    auth.refresh_if_needed()
    assert auth.authenticate({"Authorization": "Bearer new-token"}).ok is True
    assert auth.authenticate({"Authorization": "Bearer old-token"}).ok is False


def test_replay_state_tracks_progress():
    state = forwarder.ReplayState()
    state.start("raw", "last_24h", 24, False)
    state.progress(processed_delta=3, rebuilt_delta=2, signals_delta=1, alerts_delta=1)
    snapshot = state.snapshot()
    assert snapshot["in_progress"] is True
    assert snapshot["processed_records"] == 3
    state.finish(True)
    assert state.snapshot()["in_progress"] is False


# ──────────── Phase 3 — secret redaction ────────────


def test_mask_config_for_logging_redacts_expanded_field_names():
    """Each newly-added sensitive field name must be masked in dict logs."""
    sensitive_fields = [
        "authorization",
        "Bearer",
        "cookie",
        "client_secret",
        "client_id",
        "access_token",
        "refresh_token",
        "id_token",
        "api_secret",
        "private_key",
        "passphrase",
        "credential",
        "x-api-key",
        "token",
        # legacy patterns that must continue to mask
        "password",
        "API_KEY",
        "API_SECRET",
    ]
    sentinel = "real-secret-value-DO-NOT-LEAK"
    payload = {field: sentinel for field in sensitive_fields}
    payload["service_name"] = "leave-me-alone"  # control: a non-sensitive key
    masked = forwarder.mask_config_for_logging(payload)
    for field in sensitive_fields:
        assert masked[field] == "***MASKED***", f"{field} was not masked: {masked[field]}"
    assert masked["service_name"] == "leave-me-alone"
    # Sentinel must not appear anywhere in the masked dict's values.
    assert sentinel not in str(masked)


def test_mask_sensitive_text_redacts_authorization_and_kv_pairs():
    """Free-form error strings get key=value and Bearer tokens scrubbed."""
    sentinel = "AKIAEXAMPLEKEY1234567890"
    samples = [
        "Authorization: Bearer " + sentinel,
        "api.key=" + sentinel + " host=broker:9092",
        'client_secret="' + sentinel + '"',
        "password=" + sentinel,
        "x-api-key:" + sentinel,
        "access_token=" + sentinel + ";refresh_token=" + sentinel,
        "Failed: sasl.username=alice sasl.password=" + sentinel,
        "kafka error: bootstrap=broker:9092 api.secret=" + sentinel,
    ]
    for raw in samples:
        masked = forwarder.mask_sensitive_text(raw)
        assert sentinel not in masked, f"sentinel leaked in {masked!r}"
        assert "***MASKED***" in masked, f"no mask token in {masked!r}"


def test_mask_sensitive_text_handles_none_and_safe_input():
    assert forwarder.mask_sensitive_text(None) is None
    assert forwarder.mask_sensitive_text("plain text without secrets") == "plain text without secrets"


def test_delivery_callback_masks_kafka_error_before_logging(monkeypatch):
    """Kafka delivery errors that include API keys must be masked at capture
    *and* on the heartbeat log path."""

    captured = []

    class _FakeLogger:
        def error(self, msg, *args, **kwargs):
            captured.append(msg % args if args else msg)

        def info(self, msg, *args, **kwargs):
            captured.append(msg % args if args else msg)

        def warning(self, msg, *args, **kwargs):
            captured.append(msg % args if args else msg)

        def exception(self, msg, *args, **kwargs):
            captured.append(msg % args if args else msg)

        def debug(self, *args, **kwargs):  # ignored
            pass

    monkeypatch.setattr(forwarder, "logger", _FakeLogger())
    forwarder.delivery_errors["count"] = 0
    forwarder.delivery_errors["last_error"] = None

    sentinel = "AKIA-LEAKED-KEY-9999"
    fake_err = (
        "Failed to produce: connection refused; "
        f"sasl.password={sentinel}; api.key={sentinel}"
    )

    class _Msg:
        def topic(self):
            return "audit-events"

    forwarder.delivery_callback(fake_err, _Msg())

    last_error = forwarder.delivery_errors["last_error"]
    assert last_error is not None
    assert sentinel not in last_error, f"sentinel leaked into last_error: {last_error}"
    assert "***MASKED***" in last_error
    for message in captured:
        assert sentinel not in message, f"sentinel leaked into log: {message}"


def test_flatten_audit_lowercase_method_deletion():
    """Regression: Confluent internal events use lowercase method names."""
    from audit_forwarder import flatten_audit
    event = {
        "id": "test-lowercase-delete",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org-1",
        "subject": "",
        "type": "io.confluent.kafka.server/authorization",
        "time": "2026-05-13T10:00:00Z",
        "data": {
            "methodName": "deleteCluster",   # lowercase d
            "authenticationInfo": {"principal": "User:sa-abc"},
            "result": {"status": "SUCCESS"},
        },
    }
    result = flatten_audit(event)
    assert result["is_deletion"] is True, (
        "is_deletion must be True for lowercase 'deleteCluster' — "
        "case-sensitive check was the bug"
    )
