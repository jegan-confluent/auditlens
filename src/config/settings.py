"""
Configuration settings with Pydantic validation and secrets integration.

Supports loading from:
- Environment variables
- .env files
- Secrets managers (Vault, AWS SM, GCP SM)
"""

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecretsBackendType(str, Enum):
    """Supported secrets backend types."""
    ENV = "env"
    VAULT = "vault"
    AWS_SECRETS_MANAGER = "aws_secrets_manager"
    GCP_SECRET_MANAGER = "gcp_secret_manager"


class SinkType(str, Enum):
    """Supported sink types."""
    KAFKA = "kafka"
    S3 = "s3"
    GCS = "gcs"
    DLQ = "dlq"


class KafkaSourceConfig(BaseModel):
    """Source Kafka (audit log cluster) configuration."""
    bootstrap_servers: str
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    topic: str = "confluent-audit-log-events"
    group_id: str = "audit-forwarder-v2"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = True
    auto_commit_interval_ms: int = 5000
    fetch_min_bytes: int = 1
    fetch_max_bytes: int = 52428800  # 50MB
    fetch_wait_max_ms: int = 100
    max_partition_fetch_bytes: int = 10485760  # 10MB
    session_timeout_ms: int = 45000
    heartbeat_interval_ms: int = 3000


class KafkaDestConfig(BaseModel):
    """Destination Kafka configuration."""
    bootstrap_servers: str
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    topic: str = "audit-logs-processed"
    enable_idempotence: bool = True
    acks: str = "all"
    retries: int = 5
    delivery_timeout_ms: int = 300000
    linger_ms: int = 100
    batch_size: int = 524288  # 512KB
    compression_type: str = "lz4"
    buffer_memory: int = 67108864  # 64MB
    max_in_flight_requests: int = 5


class SchemaRegistryConfig(BaseModel):
    """Schema Registry configuration."""
    url: str
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    auto_register_schemas: bool = False
    cache_ttl_seconds: int = 3600


class S3SinkConfig(BaseModel):
    """S3 sink configuration."""
    enabled: bool = False
    bucket: str = ""
    prefix: str = "confluent-audit-logs/"
    region: str = "us-west-2"
    format: str = "parquet"  # parquet, json, csv
    compression: str = "snappy"  # snappy, gzip, none
    partition_by: str = "hour"  # hour, day, event_type, service
    batch_size: int = 10000
    flush_interval_seconds: int = 300
    # AWS credentials (optional - can use IAM roles)
    aws_access_key_id: Optional[str] = Field(default=None, repr=False)
    aws_secret_access_key: Optional[str] = Field(default=None, repr=False)


class GCSSinkConfig(BaseModel):
    """GCS sink configuration."""
    enabled: bool = False
    bucket: str = ""
    prefix: str = "confluent-audit-logs/"
    project_id: str = ""
    format: str = "parquet"
    compression: str = "snappy"
    partition_by: str = "hour"
    batch_size: int = 10000
    flush_interval_seconds: int = 300
    # GCP credentials (optional - can use service account)
    credentials_file: Optional[str] = None


class DLQConfig(BaseModel):
    """Dead Letter Queue configuration."""
    enabled: bool = True
    topic: str = "audit-forwarder-dlq"
    max_retries: int = 3
    retry_delay_seconds: int = 60


class QueryCacheConfig(BaseModel):
    """Query cache configuration for MCP server."""
    enabled: bool = True
    backend: str = "sqlite"  # sqlite, redis
    # SQLite
    sqlite_path: str = "./data/query_cache.db"
    # Redis
    redis_url: Optional[str] = None
    ttl_seconds: int = 3600
    max_entries: int = 100000


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 30
    half_open_requests: int = 3


class MetricsConfig(BaseModel):
    """Metrics and observability configuration."""
    enabled: bool = True
    port: int = 8003
    path: str = "/metrics"
    health_path: str = "/health"
    include_process_metrics: bool = True


class MCPConfig(BaseModel):
    """MCP server configuration."""
    enabled: bool = True
    name: str = "audit-forwarder"
    version: str = "2.1.0"  # Read from VERSION file if needed


class ProcessingConfig(BaseModel):
    """Processing configuration."""
    batch_size: int = 500
    num_workers: int = 3  # Partition-level parallelism
    heartbeat_interval_seconds: int = 30
    lag_report_interval_seconds: int = 60
    offset_commit_interval_seconds: int = 5


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "audit-forwarder"
    app_env: str = "development"  # development, staging, production
    log_level: str = "INFO"
    log_format: str = "json"  # json, text

    # Secrets backend
    secrets_backend: SecretsBackendType = SecretsBackendType.ENV
    vault_addr: Optional[str] = None
    vault_token: Optional[str] = Field(default=None, repr=False)
    vault_path: str = "secret/data/audit-forwarder"

    # Source Kafka (audit log cluster)
    audit_bootstrap: str = ""
    audit_api_key: str = Field(default="", repr=False)
    audit_api_secret: str = Field(default="", repr=False)
    audit_topic: str = "confluent-audit-log-events"
    group_id: str = "audit-forwarder-v2"

    # Destination Kafka
    dest_bootstrap: str = ""
    dest_api_key: str = Field(default="", repr=False)
    dest_api_secret: str = Field(default="", repr=False)
    dest_topic: str = "audit-logs-processed"

    # Schema Registry
    schema_registry_url: str = ""
    schema_registry_key: str = Field(default="", repr=False)
    schema_registry_secret: str = Field(default="", repr=False)

    # S3 sink
    s3_enabled: bool = False
    s3_bucket: str = ""
    s3_prefix: str = "confluent-audit-logs/"
    s3_region: str = "us-west-2"
    s3_format: str = "parquet"
    s3_compression: str = "snappy"
    aws_access_key_id: Optional[str] = Field(default=None, repr=False)
    aws_secret_access_key: Optional[str] = Field(default=None, repr=False)

    # GCS sink
    gcs_enabled: bool = False
    gcs_bucket: str = ""
    gcs_prefix: str = "confluent-audit-logs/"
    gcs_project_id: str = ""
    gcs_format: str = "parquet"
    gcs_compression: str = "snappy"
    gcs_credentials_file: Optional[str] = None

    # DLQ
    dlq_enabled: bool = True
    dlq_topic: str = "audit-forwarder-dlq"

    # Query cache
    cache_enabled: bool = True
    cache_backend: str = "sqlite"
    cache_sqlite_path: str = "./data/query_cache.db"
    cache_redis_url: Optional[str] = None

    # Processing
    batch_size: int = 500
    num_workers: int = 3
    offset_file: str = "./data/offsets.json"

    # Metrics
    metrics_port: int = 8003

    # MCP
    mcp_enabled: bool = True

    # Active sinks
    enabled_sinks: List[str] = Field(default=["kafka"])

    def get_kafka_source_config(self) -> KafkaSourceConfig:
        """Build source Kafka configuration."""
        return KafkaSourceConfig(
            bootstrap_servers=self.audit_bootstrap,
            api_key=self.audit_api_key,
            api_secret=self.audit_api_secret,
            topic=self.audit_topic,
            group_id=self.group_id,
        )

    def get_kafka_dest_config(self) -> KafkaDestConfig:
        """Build destination Kafka configuration."""
        return KafkaDestConfig(
            bootstrap_servers=self.dest_bootstrap,
            api_key=self.dest_api_key,
            api_secret=self.dest_api_secret,
            topic=self.dest_topic,
        )

    def get_schema_registry_config(self) -> SchemaRegistryConfig:
        """Build Schema Registry configuration."""
        return SchemaRegistryConfig(
            url=self.schema_registry_url,
            api_key=self.schema_registry_key,
            api_secret=self.schema_registry_secret,
        )

    def get_s3_sink_config(self) -> S3SinkConfig:
        """Build S3 sink configuration."""
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
        """Build GCS sink configuration."""
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
        """Build DLQ configuration."""
        return DLQConfig(
            enabled=self.dlq_enabled,
            topic=self.dlq_topic,
        )

    def get_cache_config(self) -> QueryCacheConfig:
        """Build query cache configuration."""
        return QueryCacheConfig(
            enabled=self.cache_enabled,
            backend=self.cache_backend,
            sqlite_path=self.cache_sqlite_path,
            redis_url=self.cache_redis_url,
        )

    def get_metrics_config(self) -> MetricsConfig:
        """Build metrics configuration."""
        return MetricsConfig(port=self.metrics_port)

    def get_processing_config(self) -> ProcessingConfig:
        """Build processing configuration."""
        return ProcessingConfig(
            batch_size=self.batch_size,
            num_workers=self.num_workers,
        )

    def validate_required(self) -> List[str]:
        """Validate required configuration and return list of missing items."""
        missing = []

        # Source Kafka is always required
        if not self.audit_bootstrap:
            missing.append("AUDIT_BOOTSTRAP")
        if not self.audit_api_key:
            missing.append("AUDIT_API_KEY")
        if not self.audit_api_secret:
            missing.append("AUDIT_API_SECRET")

        # Destination Kafka required if kafka sink enabled
        if "kafka" in self.enabled_sinks:
            if not self.dest_bootstrap:
                missing.append("DEST_BOOTSTRAP")
            if not self.dest_api_key:
                missing.append("DEST_API_KEY")
            if not self.dest_api_secret:
                missing.append("DEST_API_SECRET")
            if not self.schema_registry_url:
                missing.append("SCHEMA_REGISTRY_URL")
            if not self.schema_registry_key:
                missing.append("SCHEMA_REGISTRY_KEY")
            if not self.schema_registry_secret:
                missing.append("SCHEMA_REGISTRY_SECRET")

        # S3 required if s3 sink enabled
        if "s3" in self.enabled_sinks or self.s3_enabled:
            if not self.s3_bucket:
                missing.append("S3_BUCKET")

        # GCS required if gcs sink enabled
        if "gcs" in self.enabled_sinks or self.gcs_enabled:
            if not self.gcs_bucket:
                missing.append("GCS_BUCKET")
            if not self.gcs_project_id:
                missing.append("GCS_PROJECT_ID")

        return missing


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
