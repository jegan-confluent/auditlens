#!/usr/bin/env python3
"""Register AuditLens Avro schemas with the configured Schema Registry.

Usage:
    python scripts/register_sr_schemas.py              # register all subjects
    python scripts/register_sr_schemas.py --check-only # report versions, no writes

Required environment variables:
    SCHEMA_REGISTRY_URL         — Schema Registry HTTPS endpoint
    SCHEMA_REGISTRY_API_KEY     — API key (omit both key+secret for unauthenticated SR)
    SCHEMA_REGISTRY_API_SECRET  — API secret

Subjects:
    audit.enriched.v1-value       (compatibility forced to FORWARD)
    audit.signals.denials.v1-value
    audit.signals.highrisk.v1-value
    audit.alerts.v1-value
    audit.dlq.v1-value

The enriched topic is FORWARD because AuditLens adds new fields whenever
Confluent ships a new audit method or we add a new enrichment column.
Other topics keep the registry default (BACKWARD).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
    from confluent_kafka.schema_registry.error import SchemaRegistryError
except ImportError:
    print(
        "ERROR: confluent_kafka.schema_registry is not installed. "
        "Run `pip install -r requirements.txt` inside the venv.",
        file=sys.stderr,
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

NAMESPACE = "io.confluent.auditlens"
FORWARD = "FORWARD"


def _load_avsc(path: Path) -> str:
    with path.open("r", encoding="utf-8") as fp:
        return json.dumps(json.load(fp))


def _signal_schema(record_name: str, doc: str) -> str:
    return json.dumps({
        "type": "record",
        "namespace": NAMESPACE,
        "name": record_name,
        "doc": doc,
        "fields": [
            {"name": "_schema_version", "type": "string", "default": "1.0"},
            {"name": "event_fingerprint", "type": "string",
             "doc": "Per-event SHA-256 fingerprint. Matches audit.enriched.v1 for join keys."},
            {"name": "timestamp",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None,
             "doc": "Original event time. UTC milliseconds."},
            {"name": "ingested_at",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None,
             "doc": "When the forwarder ingested this event."},
            {"name": "actor", "type": ["null", "string"], "default": None},
            {"name": "actor_display_name", "type": ["null", "string"], "default": None},
            {"name": "action", "type": ["null", "string"], "default": None},
            {"name": "resource_name", "type": ["null", "string"], "default": None},
            {"name": "source_ip", "type": ["null", "string"], "default": None},
            {"name": "environment_id", "type": ["null", "string"], "default": None},
            {"name": "cluster_id", "type": ["null", "string"], "default": None},
            {"name": "signal_type", "type": ["null", "string"], "default": None},
            {"name": "signal_reason", "type": ["null", "string"], "default": None},
            {"name": "risk_level", "type": ["null", "string"], "default": None},
            {"name": "is_denied", "type": ["null", "boolean"], "default": None},
            {"name": "is_failure", "type": ["null", "boolean"], "default": None},
            {"name": "raw_payload_json", "type": ["null", "string"], "default": None,
             "doc": "Full original event for replay."},
        ],
    })


def _alert_schema() -> str:
    return json.dumps({
        "type": "record",
        "namespace": NAMESPACE,
        "name": "AuditAlert",
        "doc": "Per-event operator alert (Slack/Teams/PagerDuty/webhook destinations consume this).",
        "fields": [
            {"name": "_schema_version", "type": "string", "default": "1.0"},
            {"name": "event_fingerprint", "type": "string",
             "doc": "Per-event SHA-256 fingerprint."},
            {"name": "alert_timestamp",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None,
             "doc": "When the alert was emitted by the forwarder."},
            {"name": "severity", "type": ["null", "string"], "default": None,
             "doc": "CRITICAL | HIGH | MEDIUM | LOW."},
            {"name": "title", "type": ["null", "string"], "default": None},
            {"name": "message", "type": ["null", "string"], "default": None},
            {"name": "actor", "type": ["null", "string"], "default": None},
            {"name": "action", "type": ["null", "string"], "default": None},
            {"name": "resource_name", "type": ["null", "string"], "default": None},
            {"name": "signal_type", "type": ["null", "string"], "default": None},
            {"name": "risk_level", "type": ["null", "string"], "default": None},
            {"name": "raw_payload_json", "type": ["null", "string"], "default": None},
        ],
    })


def _dlq_schema() -> str:
    return json.dumps({
        "type": "record",
        "namespace": NAMESPACE,
        "name": "AuditDlq",
        "doc": "Dead-letter envelope for events that failed processing.",
        "fields": [
            {"name": "_schema_version", "type": "string", "default": "1.0"},
            {"name": "ingested_at",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None},
            {"name": "error_type", "type": ["null", "string"], "default": None},
            {"name": "error_message", "type": ["null", "string"], "default": None},
            {"name": "source_topic", "type": ["null", "string"], "default": None},
            {"name": "source_partition", "type": ["null", "int"], "default": None},
            {"name": "source_offset", "type": ["null", "long"], "default": None},
            {"name": "retry_count", "type": ["null", "int"], "default": None},
            {"name": "first_failure",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None},
            {"name": "last_failure",
             "type": ["null", {"type": "long", "logicalType": "timestamp-millis"}],
             "default": None},
            {"name": "raw_payload_json", "type": ["null", "string"], "default": None,
             "doc": "Original event payload for replay after the underlying defect is fixed."},
        ],
    })


def _make_client(url: str, key: Optional[str], secret: Optional[str]) -> SchemaRegistryClient:
    conf: dict = {"url": url}
    if key and secret:
        conf["basic.auth.user.info"] = f"{key}:{secret}"
    return SchemaRegistryClient(conf)


def _not_found(exc: SchemaRegistryError) -> bool:
    """SR returns either http 404 or Confluent code 40401 when the subject
    has never been registered."""
    code = getattr(exc, "error_code", None)
    status = getattr(exc, "http_status_code", None)
    return code == 40401 or status == 404


def _get_latest(client: SchemaRegistryClient, subject: str):
    try:
        return client.get_latest_version(subject)
    except SchemaRegistryError as exc:
        if _not_found(exc):
            return None
        raise


def _register(client: SchemaRegistryClient, subject: str, schema_str: str):
    """Register an Avro schema for ``subject`` and report what happened.

    Returns (status, schema_id, version, previous_version) where
    ``status`` is REGISTERED | SKIPPED | UPDATED.
    """
    pre = _get_latest(client, subject)
    schema_id = client.register_schema(subject, Schema(schema_str, schema_type="AVRO"))
    post = client.get_latest_version(subject)
    if pre is None:
        return "REGISTERED", schema_id, post.version, None
    if pre.schema_id == schema_id:
        return "SKIPPED", schema_id, pre.version, None
    return "UPDATED", schema_id, post.version, pre.version


def _set_compatibility(client: SchemaRegistryClient, subject: str, level: str) -> bool:
    try:
        client.set_compatibility(subject_name=subject, level=level)
        return True
    except SchemaRegistryError as exc:
        print(f"ERROR     [{subject}] failed to set compatibility {level}: {exc}", file=sys.stderr)
        return False


def _plan() -> list[tuple[str, str, Optional[str]]]:
    enriched_path = SCHEMAS_DIR / "audit_enriched_v1.avsc"
    if not enriched_path.exists():
        raise FileNotFoundError(
            f"audit_enriched_v1.avsc not found at {enriched_path}. "
            "Run from the repo root after creating the .avsc file."
        )
    return [
        ("audit.enriched.v1-value",         _load_avsc(enriched_path),                                   FORWARD),
        ("audit.signals.denials.v1-value",  _signal_schema("AuditDenialSignal", "Denial signal stream."),  None),
        ("audit.signals.highrisk.v1-value", _signal_schema("AuditHighRiskSignal", "High-risk signal stream."), None),
        ("audit.alerts.v1-value",           _alert_schema(),                                            None),
        ("audit.dlq.v1-value",              _dlq_schema(),                                              None),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-only", action="store_true",
                        help="Report current schema versions without registering.")
    args = parser.parse_args()

    url = (os.environ.get("SCHEMA_REGISTRY_URL") or "").strip()
    key = (os.environ.get("SCHEMA_REGISTRY_API_KEY") or "").strip()
    secret = (os.environ.get("SCHEMA_REGISTRY_API_SECRET") or "").strip()

    if not url:
        print("ERROR: SCHEMA_REGISTRY_URL is not set", file=sys.stderr)
        return 1
    if (key and not secret) or (secret and not key):
        print(
            "ERROR: SCHEMA_REGISTRY_API_KEY and SCHEMA_REGISTRY_API_SECRET "
            "must be set together (or both unset for unauthenticated SR).",
            file=sys.stderr,
        )
        return 1

    try:
        plan = _plan()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    client = _make_client(url, key or None, secret or None)

    if args.check_only:
        any_fail = False
        for subject, _, _ in plan:
            try:
                current = _get_latest(client, subject)
            except SchemaRegistryError as exc:
                print(f"[ERROR]          {subject}: {exc}", file=sys.stderr)
                any_fail = True
                continue
            except Exception as exc:
                print(f"[ERROR]          {subject}: {exc}", file=sys.stderr)
                any_fail = True
                continue
            if current is None:
                print(f"[NOT REGISTERED] {subject}")
            else:
                print(f"[VERSION]        {subject}  id={current.schema_id}  version={current.version}")
        return 1 if any_fail else 0

    exit_code = 0
    for subject, schema_str, compat in plan:
        try:
            status, schema_id, version, prev = _register(client, subject, schema_str)
        except SchemaRegistryError as exc:
            print(f"[ERROR]      {subject}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        except Exception as exc:
            print(f"[ERROR]      {subject}: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        if status == "REGISTERED":
            print(f"[REGISTERED] {subject}  id={schema_id}  version={version}")
        elif status == "SKIPPED":
            print(f"[SKIPPED]    {subject}  already at version {version}")
        elif status == "UPDATED":
            print(f"[UPDATED]    {subject}  v{prev}->v{version} (new fields added)  id={schema_id}")

        if compat:
            if _set_compatibility(client, subject, compat):
                print(f"[COMPAT SET] {subject}  {compat}")
            else:
                exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
