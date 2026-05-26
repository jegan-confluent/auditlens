"""Schema Registry client — optional Avro serialization for audit.enriched.v1.

If SCHEMA_REGISTRY_URL is not set the module works in degraded mode:
get_sr_client() returns None and callers fall back to JSON production.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("auditlens.schema_registry")

# Accept both naming conventions: new API_KEY style and existing KEY style.
SR_URL = os.getenv("SCHEMA_REGISTRY_URL", "")
SR_API_KEY = (
    os.getenv("SCHEMA_REGISTRY_API_KEY")
    or os.getenv("SCHEMA_REGISTRY_KEY")
    or ""
)
SR_API_SECRET = (
    os.getenv("SCHEMA_REGISTRY_API_SECRET")
    or os.getenv("SCHEMA_REGISTRY_SECRET")
    or ""
)

# Avro schema fields for audit.enriched.v1 — used to project dicts before
# serialization so extra fields from flatten_audit() are silently dropped.
_ENRICHED_FIELDS = {
    # NOTE: "id" intentionally NOT included — the new Avro schema
    # (consolidation 2026-05-26) does not declare an id field, so
    # projecting it would cause AvroSerializer to reject the message.
    "event_fingerprint", "timestamp", "schema_version",
    "pipeline_stage", "event_contract_version", "result", "actor",
    "actor_id", "actor_display_name", "actor_email", "actor_type",
    "actor_source", "actor_confidence", "actor_enriched_at", "action",
    "normalized_action", "action_category", "resource_type", "resource_name",
    "resource_display", "resource_display_name", "cluster_id", "cluster_name",
    "source_ip", "source_context", "client_id", "connection_id", "request_id",
    "environment_id", "environment_name", "parent_resource", "resource_scope",
    "resource_criticality", "blast_radius_hint", "production_hint",
    "flink_region", "network_id", "summary", "is_failure", "is_denied",
    "is_routine_noise", "is_high_risk", "signal_type", "signal_reason",
    "impact_type", "risk_level", "change_type", "resource_family",
    "event_title", "event_summary", "decision_reason", "decision_label",
    "recommended_action", "client_tool",
    # New fields added 2026-05-26 consolidation — flattened auth subfields
    # (migration 0023), envelope ingested_at, raw Confluent methodName.
    "access_type", "auth_granted", "auth_operation",
    "auth_pattern_type", "auth_resource_type",
    "ingested_at", "methodName", "result_resource_id",
}


def get_sr_client():
    """Return a SchemaRegistryClient if SR_URL is configured, else None."""
    if not SR_URL:
        logger.debug("SCHEMA_REGISTRY_URL not set — SR disabled")
        return None
    try:
        from confluent_kafka.schema_registry import SchemaRegistryClient  # type: ignore
        conf: dict[str, Any] = {"url": SR_URL}
        if SR_API_KEY and SR_API_SECRET:
            conf["basic.auth.user.info"] = f"{SR_API_KEY}:{SR_API_SECRET}"
        client = SchemaRegistryClient(conf)
        logger.info("Schema Registry client created — url=%s", SR_URL)
        return client
    except Exception as exc:
        logger.warning("Schema Registry client creation failed: %s", exc)
        return None


def register_schema(client: Any, subject: str, schema_path: str) -> int:
    """Register schema from .avsc file. Returns schema ID.

    Uses BACKWARD compatibility — safe for adding optional fields.
    """
    from confluent_kafka.schema_registry import Schema  # type: ignore
    with open(schema_path) as f:
        schema_str = f.read()
    schema = Schema(schema_str, "AVRO")
    schema_id = client.register_schema(subject, schema)
    logger.info("Registered schema subject=%s id=%d", subject, schema_id)
    return schema_id


def get_avro_serializer(client: Any, schema_path: str) -> Any:
    """Return an AvroSerializer for the given .avsc file.

    auto.register.schemas is forced OFF — schema registration is now
    owned by `make register-schemas` (scripts/register_sr_schemas.py)
    so the FORWARD compatibility check we set on the subject cannot be
    bypassed by an auto-register at produce time.
    """
    from confluent_kafka.schema_registry.avro import AvroSerializer  # type: ignore
    with open(schema_path) as f:
        schema_str = f.read()
    return AvroSerializer(client, schema_str, conf={"auto.register.schemas": False})


def project_enriched(event: dict[str, Any]) -> dict[str, Any]:
    """Project an enriched event dict to only the fields in audit_enriched_v1.avsc.

    Extra keys from flatten_audit() (specversion, methodName, etc.) are dropped
    so AvroSerializer does not raise on unexpected fields.
    """
    return {k: event.get(k) for k in _ENRICHED_FIELDS}
