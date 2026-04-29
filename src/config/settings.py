"""
Canonical AuditLens foundation configuration.

This module exists to keep one clear environment contract across Docker,
Kubernetes, and local runs. The forwarder remains the runtime source of truth;
these settings mirror that contract for validation and auxiliary modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional


def _env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    return value if value is not None else ""


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


@dataclass(frozen=True)
class KafkaSourceConfig:
    bootstrap_servers: str
    api_key: str
    api_secret: str
    topic: str = "confluent-audit-log-events"
    group_id: str = "auditlens-forwarder-v1"
    auto_offset_reset: str = "latest"
    enable_auto_commit: bool = False


@dataclass(frozen=True)
class KafkaDestConfig:
    bootstrap_servers: str
    api_key: str
    api_secret: str
    topic: str = "audit.enriched.v1"
    enable_idempotence: bool = True
    acks: str = "all"
    retries: int = 3
    delivery_timeout_ms: int = 120000
    linger_ms: int = 10
    batch_size: int = 2 * 1024 * 1024
    compression_type: str = "lz4"
    buffer_memory: int = 3 * 1024 * 1024 * 1024
    max_in_flight_requests: int = 5


@dataclass(frozen=True)
class SchemaRegistryConfig:
    url: str = ""
    api_key: str = ""
    api_secret: str = ""
    auto_register_schemas: bool = False


@dataclass(frozen=True)
class S3SinkConfig:
    enabled: bool = False
    bucket: str = ""
    prefix: str = "auditlens/"
    region: str = "us-west-2"
    format: str = "parquet"
    compression: str = "snappy"
    partition_by: str = "hour"
    batch_size: int = 10000
    flush_interval_seconds: int = 300
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None


@dataclass(frozen=True)
class GCSSinkConfig:
    enabled: bool = False
    bucket: str = ""
    prefix: str = "auditlens/"
    project_id: str = ""
    format: str = "parquet"
    compression: str = "snappy"
    partition_by: str = "hour"
    batch_size: int = 10000
    flush_interval_seconds: int = 300
    credentials_file: Optional[str] = None


@dataclass(frozen=True)
class DLQConfig:
    enabled: bool = True
    topic: str = "audit.dlq.v1"
    max_retries: int = 3
    retry_delay_seconds: int = 60


@dataclass(frozen=True)
class QueryCacheConfig:
    enabled: bool = False
    backend: str = "sqlite"
    sqlite_path: str = "/tmp/auditlens-query-cache.db"
    redis_url: Optional[str] = None
    ttl_seconds: int = 3600
    max_entries: int = 100000


@dataclass(frozen=True)
class MetricsConfig:
    enabled: bool = True
    port: int = 8003
    path: str = "/metrics"
    health_path: str = "/health"


@dataclass(frozen=True)
class ProcessingConfig:
    batch_size: int = 5000
    num_workers: int = 1
    offset_commit_interval_seconds: int = 5


class Settings:
    """Canonical environment-backed settings for the AuditLens foundation."""

    def __init__(self) -> None:
        self.app_name = _env("APP_NAME", "AuditLens")
        self.app_env = _env("APP_ENV", "development")
        self.log_level = _env("LOG_LEVEL", "INFO")
        self.log_format = _env("LOG_FORMAT", "json")

        self.audit_bootstrap = _env("AUDIT_BOOTSTRAP")
        self.audit_api_key = _env("AUDIT_API_KEY")
        self.audit_api_secret = _env("AUDIT_API_SECRET")
        self.audit_topic = _env("AUDIT_TOPIC", "confluent-audit-log-events")
        self.group_id = _env("GROUP_ID", "auditlens-forwarder-v1")
        self.auto_offset_reset = _env("AUTO_OFFSET_RESET", "latest")

        self.dest_bootstrap = _env("DEST_BOOTSTRAP")
        self.dest_api_key = _env("DEST_API_KEY")
        self.dest_api_secret = _env("DEST_API_SECRET")

        self.audit_raw_topic = _env("AUDIT_RAW_TOPIC", "audit.raw.v1")
        self.audit_normalized_topic = _env("AUDIT_NORMALIZED_TOPIC", "audit.normalized.v1")
        self.audit_enriched_topic = _env("AUDIT_ENRICHED_TOPIC", "audit.enriched.v1")
        self.audit_signals_denials_topic = _env("AUDIT_SIGNALS_DENIALS_TOPIC", "audit.signals.denials.v1")
        self.audit_signals_highrisk_topic = _env("AUDIT_SIGNALS_HIGHRISK_TOPIC", "audit.signals.highrisk.v1")
        self.audit_alerts_topic = _env("AUDIT_ALERTS_TOPIC", "audit.alerts.v1")
        self.dlq_topic = _env("DLQ_TOPIC", "audit.dlq.v1")

        self.schema_registry_url = _env("SCHEMA_REGISTRY_URL")
        self.schema_registry_key = _env("SCHEMA_REGISTRY_KEY")
        self.schema_registry_secret = _env("SCHEMA_REGISTRY_SECRET")

        self.s3_enabled = _bool_env("S3_ENABLED", False)
        self.s3_bucket = _env("S3_BUCKET")
        self.s3_prefix = _env("S3_PREFIX", "auditlens/")
        self.s3_region = _env("S3_REGION", "us-west-2")
        self.s3_format = _env("S3_FORMAT", "parquet")
        self.s3_compression = _env("S3_COMPRESSION", "snappy")
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        self.gcs_enabled = _bool_env("GCS_ENABLED", False)
        self.gcs_bucket = _env("GCS_BUCKET")
        self.gcs_prefix = _env("GCS_PREFIX", "auditlens/")
        self.gcs_project_id = _env("GCS_PROJECT_ID")
        self.gcs_format = _env("GCS_FORMAT", "parquet")
        self.gcs_compression = _env("GCS_COMPRESSION", "snappy")
        self.gcs_credentials_file = os.getenv("GCS_CREDENTIALS_FILE")

        self.dlq_enabled = _bool_env("ENABLE_DLQ", True)
        self.cache_enabled = _bool_env("CACHE_ENABLED", False)
        self.cache_backend = _env("CACHE_BACKEND", "sqlite")
        self.cache_sqlite_path = _env("CACHE_SQLITE_PATH", "/tmp/auditlens-query-cache.db")
        self.cache_redis_url = os.getenv("CACHE_REDIS_URL")

        self.batch_size = _int_env("FORWARDER_BATCH_SIZE", 5000)
        self.num_workers = _int_env("NUM_WORKERS", 1)
        self.metrics_port = _int_env("METRICS_PORT", 8003)

        self.enable_denial_aggregation = _bool_env("ENABLE_DENIAL_AGGREGATION", True)
        self.alert_on_high_risk = _bool_env("ALERT_ON_HIGH_RISK", True)
        self.enabled_sinks = ["kafka"]
        if self.s3_enabled:
            self.enabled_sinks.append("s3")
        if self.gcs_enabled:
            self.enabled_sinks.append("gcs")

    def get_kafka_source_config(self) -> KafkaSourceConfig:
        return KafkaSourceConfig(
            bootstrap_servers=self.audit_bootstrap,
            api_key=self.audit_api_key,
            api_secret=self.audit_api_secret,
            topic=self.audit_topic,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
        )

    def get_kafka_dest_config(self) -> KafkaDestConfig:
        return KafkaDestConfig(
            bootstrap_servers=self.dest_bootstrap,
            api_key=self.dest_api_key,
            api_secret=self.dest_api_secret,
            topic=self.audit_enriched_topic,
        )

    def get_schema_registry_config(self) -> SchemaRegistryConfig:
        return SchemaRegistryConfig(
            url=self.schema_registry_url,
            api_key=self.schema_registry_key,
            api_secret=self.schema_registry_secret,
        )

    def get_s3_sink_config(self) -> S3SinkConfig:
        return S3SinkConfig(
            enabled=self.s3_enabled,
            bucket=self.s3_bucket,
            prefix=self.s3_prefix,
            region=self.s3_region,
            format=self.s3_format,
            compression=self.s3_compression,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )

    def get_gcs_sink_config(self) -> GCSSinkConfig:
        return GCSSinkConfig(
            enabled=self.gcs_enabled,
            bucket=self.gcs_bucket,
            prefix=self.gcs_prefix,
            project_id=self.gcs_project_id,
            format=self.gcs_format,
            compression=self.gcs_compression,
            credentials_file=self.gcs_credentials_file,
        )

    def get_dlq_config(self) -> DLQConfig:
        return DLQConfig(enabled=self.dlq_enabled, topic=self.dlq_topic)

    def get_cache_config(self) -> QueryCacheConfig:
        return QueryCacheConfig(
            enabled=self.cache_enabled,
            backend=self.cache_backend,
            sqlite_path=self.cache_sqlite_path,
            redis_url=self.cache_redis_url,
        )

    def get_metrics_config(self) -> MetricsConfig:
        return MetricsConfig(port=self.metrics_port)

    def get_processing_config(self) -> ProcessingConfig:
        return ProcessingConfig(batch_size=self.batch_size, num_workers=self.num_workers)

    def topic_contract(self) -> Dict[str, str]:
        return {
            "audit.raw.v1": self.audit_raw_topic,
            "audit.normalized.v1": self.audit_normalized_topic,
            "audit.enriched.v1": self.audit_enriched_topic,
            "audit.signals.denials.v1": self.audit_signals_denials_topic,
            "audit.signals.highrisk.v1": self.audit_signals_highrisk_topic,
            "audit.alerts.v1": self.audit_alerts_topic,
            "audit.dlq.v1": self.dlq_topic,
        }

    def validate_required(self) -> List[str]:
        missing: List[str] = []

        for key, value in {
            "AUDIT_BOOTSTRAP": self.audit_bootstrap,
            "AUDIT_API_KEY": self.audit_api_key,
            "AUDIT_API_SECRET": self.audit_api_secret,
            "DEST_BOOTSTRAP": self.dest_bootstrap,
            "DEST_API_KEY": self.dest_api_key,
            "DEST_API_SECRET": self.dest_api_secret,
        }.items():
            if not value:
                missing.append(key)

        if self.s3_enabled and not self.s3_bucket:
            missing.append("S3_BUCKET")
        if self.gcs_enabled and not self.gcs_bucket:
            missing.append("GCS_BUCKET")
        if self.gcs_enabled and not self.gcs_project_id:
            missing.append("GCS_PROJECT_ID")

        return missing


@lru_cache()
def get_settings() -> Settings:
    return Settings()
