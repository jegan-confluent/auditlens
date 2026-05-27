"""Settings API — GET/PUT/DELETE/test for the app_settings table.

Secrets are always returned masked (••••{last4}); never decrypted.
ADMIN token required for cold_storage category.
VIEWER token sufficient for retention category reads.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.routes.admin import require_admin
from backend.app.db.database import get_db
from backend.app.services import settings_service

router = APIRouter(tags=["settings"])

# Known categories and their key schemas (is_secret flag per key)
_SECRET_KEYS: dict[str, set[str]] = {
    "cold_storage": {"aws_secret_key", "gcs_credentials"},
    "notifications": {"webhook_url"},
    "schema_registry": {"api_key", "api_secret"},
}


def _is_secret(category: str, key: str) -> bool:
    return key in _SECRET_KEYS.get(category, set())


class SettingPutRequest(BaseModel):
    value: str
    is_secret: bool = False


@router.get("/settings/{category}")
def get_settings_category(
    category: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return settings_service.get_category(db, category)


@router.put("/settings/{category}/{key}")
def put_setting(
    category: str,
    key: str,
    payload: SettingPutRequest = Body(...),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if not (payload.value.strip() if isinstance(payload.value, str) else payload.value):
        raise HTTPException(status_code=400, detail="value must not be empty")
    # Determine is_secret from known schema, or use caller-provided flag
    is_secret = payload.is_secret or _is_secret(category, key)
    settings_service.set(db, category, key, payload.value, is_secret=is_secret)
    return {
        "category": category,
        "key": key,
        "is_set": True,
        "masked": settings_service.get_masked(db, category, key),
        "is_secret": is_secret,
    }


@router.delete("/settings/{category}/{key}")
def delete_setting(
    category: str,
    key: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    existed = settings_service.delete(db, category, key)
    return {"deleted": existed, "category": category, "key": key}


@router.post("/settings/cold-storage/test")
def test_cold_storage(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    try:
        from backend.app.services.cold_storage_service import get_backend
        backend = get_backend(db)
        ok, message = backend.test_connection()
        return {"success": ok, "message": message}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.post("/settings/notifications/test")
def test_notification(
    body: dict = Body(default={}),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Send a real test notification to every enabled destination in
    notifications.yml. Returns per-destination pass/fail + an aggregate
    count so the operator can verify wiring without an inbox of stub
    success messages.
    """
    from datetime import datetime, timezone
    try:
        from src.notifications.notifier import AuditLensNotifier
    except Exception as exc:
        return {
            "success": False,
            "message": f"notifier module import failed: {exc}",
            "results": [],
            "sent_count": 0,
            "error_count": 1,
        }

    config_path = os.environ.get("NOTIFICATIONS_CONFIG_PATH") or os.environ.get("NOTIFICATIONS_CONFIG") or "notifications.yml"
    try:
        notifier = AuditLensNotifier(config_path=config_path)
    except Exception as exc:
        return {
            "success": False,
            "message": f"failed to load {config_path}: {exc}",
            "results": [],
            "sent_count": 0,
            "error_count": 1,
        }

    if not notifier.has_destinations():
        return {
            "success": True,
            "results": [],
            "sent_count": 0,
            "error_count": 0,
            "warning": "No notification destinations configured",
        }

    test_payload = {
        "signal_type": "action_required",
        "signal_reason": "test_notification",
        "event_title": "AuditLens test notification",
        "event_summary": (
            "This is a test message from AuditLens Settings. If you see "
            "this, your notification destination is configured correctly."
        ),
        "actor": "auditlens-system",
        "actor_display_name": "AuditLens System",
        "action": "TestNotification",
        "resource_name": "notification-test",
        "environment_name": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_test": True,
    }

    results = notifier.send_test(test_payload)
    sent_count = sum(1 for r in results if r.get("status") == "sent")
    error_count = sum(1 for r in results if r.get("status") == "error")

    return {
        "success": error_count == 0 and sent_count > 0,
        "results": results,
        "sent_count": sent_count,
        "error_count": error_count,
    }


def _get_sr_creds(db: Session) -> tuple[str, str, str]:
    """Return (url, api_key, api_secret) from settings table, falling back to env vars.
    Env-var fan-out matches src/forwarder/config.py + src/product/schema_registry.py
    so a single SR_* short-form in .env works everywhere.
    """
    url = (
        settings_service.get(db, "schema_registry", "url")
        or os.environ.get("SCHEMA_REGISTRY_URL")
        or os.environ.get("SR_ENDPOINT")
        or ""
    )
    api_key = (
        settings_service.get(db, "schema_registry", "api_key")
        or os.environ.get("SCHEMA_REGISTRY_API_KEY")
        or os.environ.get("SCHEMA_REGISTRY_KEY")
        or os.environ.get("SR_API_KEY")
        or ""
    )
    api_secret = (
        settings_service.get(db, "schema_registry", "api_secret")
        or os.environ.get("SCHEMA_REGISTRY_API_SECRET")
        or os.environ.get("SCHEMA_REGISTRY_SECRET")
        or os.environ.get("SR_API_SECRET")
        or ""
    )
    return url, api_key, api_secret


@router.get("/settings/schema_registry/status")
async def get_sr_status(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    url, api_key, api_secret = _get_sr_creds(db)
    if not url:
        return {
            "configured": False,
            "url": None,
            "subjects": [],
            "error": None,
            "drift_detected": False,
            "drift_detail": None,
        }
    base = _sr_base(url)
    auth = _sr_auth(api_key, api_secret)
    try:
        # N+1 calls — fine for typical SR with <20 subjects per cluster.
        # AsyncClient keeps the connection pool warm for the inner loop.
        async with httpx.AsyncClient(auth=auth, timeout=_SR_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{base}/subjects")
            resp.raise_for_status()
            all_subject_names: list[str] = resp.json() or []
            # Filter to AuditLens-owned subjects. An SR cluster shared with
            # other apps can list dozens of unrelated subjects; surfacing
            # them in the UI made the registered-subjects table noisy and
            # broke the "is audit.enriched.v1-value registered?" check
            # downstream consumers do against subjects[].
            subject_names = [s for s in all_subject_names if s.startswith("audit.")]

            subjects: list[dict] = []
            enriched_registered_schema_str: str | None = None
            for name in subject_names:
                latest = await client.get(f"{base}/subjects/{name}/versions/latest")
                if latest.status_code == 200:
                    body = latest.json()
                    subjects.append({
                        "name": name,
                        "schema_id": body.get("id"),
                        "version": body.get("version"),
                    })
                    if name == "audit.enriched.v1-value":
                        # Capture the registered schema string so we can
                        # compare it to the on-disk .avsc for drift detection.
                        enriched_registered_schema_str = body.get("schema")
                else:
                    # Subject exists but the latest-version probe failed
                    # (rare — usually permissions). Surface the name only.
                    subjects.append({"name": name, "schema_id": None, "version": None})

        drift_detected, drift_detail = _compute_sr_drift(enriched_registered_schema_str)

        return {
            "configured": True,
            "url": url,
            "subjects": subjects,
            "error": None,
            "drift_detected": drift_detected,
            "drift_detail": drift_detail,
        }
    except Exception as exc:
        return {
            "configured": True,
            "url": url,
            "subjects": [],
            "error": str(exc),
            "drift_detected": False,
            "drift_detail": None,
        }


def _compute_sr_drift(registered_schema_str: str | None) -> tuple[bool, str | None]:
    """Compare the canonical hash of src/schema/audit_enriched_v1.avsc on disk
    with the canonical hash of the schema currently registered at SR. If they
    differ → drift detected. If the subject is missing or SR is unreachable
    → no drift (we already surface those failures elsewhere; we should not
    false-alarm on top of them).
    """
    if not registered_schema_str:
        return False, None
    import hashlib
    enriched_path = _sr_enriched_avsc_path()
    if not enriched_path.is_file():
        return False, None
    try:
        local_text = enriched_path.read_text(encoding="utf-8")
        local_canonical = json.dumps(json.loads(local_text), sort_keys=True)
        local_hash = hashlib.sha256(local_canonical.encode("utf-8")).hexdigest()
    except (OSError, json.JSONDecodeError):
        return False, None
    try:
        registered_canonical = json.dumps(json.loads(registered_schema_str), sort_keys=True)
        registered_hash = hashlib.sha256(registered_canonical.encode("utf-8")).hexdigest()
    except json.JSONDecodeError:
        # SR returned something we can't parse — be silent rather than alarmist.
        return False, None
    if local_hash != registered_hash:
        return True, (
            "Local audit_enriched_v1.avsc differs from the registered version. "
            "Click Register schemas to sync."
        )
    return False, None


@router.post("/settings/test_sr")
async def test_sr(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    url, api_key, api_secret = _get_sr_creds(db)
    if not url:
        return {"ok": False, "latency_ms": None, "error": "Schema Registry URL not configured"}
    base = _sr_base(url)
    auth = _sr_auth(api_key, api_secret)
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(auth=auth, timeout=_SR_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{base}/subjects")
            resp.raise_for_status()
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": None, "error": str(exc)}


# ──────────── Schema Registry: register schemas from UI ────────────
# Mirrors scripts/register_sr_schemas.py so operators can click a button
# from the Settings tab instead of SSH'ing to run `make register-schemas`.
# Keep the inline signal/alert/dlq schemas in sync with the CLI script;
# the enriched schema is loaded from disk so there's only ONE copy of that.

_SR_AVRO_NAMESPACE = "io.confluent.auditlens"

# SR REST API timeout + content type. The API container only has httpx
# (no confluent-kafka), so all SR calls go through the REST endpoint
# directly. application/vnd.schemaregistry.v1+json is the spec content
# type; Confluent Cloud also accepts application/json but the vendor
# media type is what `confluent_kafka.schema_registry` ships.
_SR_TIMEOUT_SECONDS = 15.0
_SR_CONTENT_TYPE = "application/vnd.schemaregistry.v1+json"


def _sr_base(url: str) -> str:
    return url.rstrip("/")


def _sr_auth(api_key: str, api_secret: str) -> tuple[str, str] | None:
    return (api_key, api_secret) if api_key and api_secret else None


def _canonical_avro(schema_str: str) -> str:
    """Deterministic JSON for skip-detection.

    SR has its own normalization (default-value handling, etc), so a
    false UPDATED is harmless — it just triggers a POST that SR will
    dedupe back to the same schema_id. We only use this for the
    pre-POST short-circuit so a benign whitespace difference does not
    bump the version.
    """
    try:
        return json.dumps(json.loads(schema_str), sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return schema_str


def _sr_signal_schema(record_name: str, doc: str) -> str:
    """Inline Avro schema for signal-stream topics. Must match
    scripts/register_sr_schemas.py:_signal_schema() exactly so re-running
    `make register-schemas` after a UI register produces the same SR
    content-hash (== a SKIPPED, not an unnecessary new version)."""
    return json.dumps({
        "type": "record",
        "namespace": _SR_AVRO_NAMESPACE,
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


def _sr_alert_schema() -> str:
    return json.dumps({
        "type": "record",
        "namespace": _SR_AVRO_NAMESPACE,
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


def _sr_dlq_schema() -> str:
    return json.dumps({
        "type": "record",
        "namespace": _SR_AVRO_NAMESPACE,
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


def _sr_enriched_avsc_path() -> Path:
    """Resolve the runtime location of audit_enriched_v1.avsc.

    The forwarder loads from src/schema/ (the docker-mounted runtime
    location) so registration should target the same file — otherwise
    the producer's serializer would expect a schema content the SR
    doesn't have. AUDITLENS_SCHEMA_DIR overrides for tests.
    """
    return Path(
        os.getenv(
            "AUDITLENS_SCHEMA_DIR",
            str(Path(__file__).resolve().parents[4] / "src" / "schema"),
        )
    ) / "audit_enriched_v1.avsc"


@router.post("/settings/schema_registry/register")
async def register_sr_schemas(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Register Avro schemas for every AuditLens-produced topic with SR.
    Mirrors `make register-schemas`. Idempotent — when the on-disk schema
    already matches the registered latest version we short-circuit before
    POSTing and report SKIPPED. Sets FORWARD compatibility on
    audit.enriched.v1-value only; other subjects keep the registry
    default (BACKWARD).

    The API container ships httpx but not confluent-kafka, so this calls
    the SR REST API directly.
    """
    url, api_key, api_secret = _get_sr_creds(db)
    if not url:
        raise HTTPException(status_code=400, detail="Schema Registry URL not configured")

    enriched_path = _sr_enriched_avsc_path()
    if not enriched_path.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"audit_enriched_v1.avsc not found at {enriched_path}",
        )
    # Re-serialize through json.dumps so we send canonical JSON to SR
    # (matches scripts/register_sr_schemas.py:_load_avsc).
    enriched_str = json.dumps(json.loads(enriched_path.read_text(encoding="utf-8")))

    plan: list[tuple[str, str, str | None]] = [
        ("audit.enriched.v1-value",         enriched_str,                                                       "FORWARD"),
        ("audit.signals.denials.v1-value",  _sr_signal_schema("AuditDenialSignal", "Denial signal stream."),     None),
        ("audit.signals.highrisk.v1-value", _sr_signal_schema("AuditHighRiskSignal", "High-risk signal stream."), None),
        ("audit.alerts.v1-value",           _sr_alert_schema(),                                                 None),
        ("audit.dlq.v1-value",              _sr_dlq_schema(),                                                   None),
    ]

    base = _sr_base(url)
    auth = _sr_auth(api_key, api_secret)
    headers = {"Content-Type": _SR_CONTENT_TYPE, "Accept": _SR_CONTENT_TYPE}

    results: list[dict[str, Any]] = []
    overall_ok = True
    async with httpx.AsyncClient(auth=auth, timeout=_SR_TIMEOUT_SECONDS, headers=headers) as client:
        for subject, schema_str, compat_level in plan:
            result = await _register_one_subject(client, base, subject, schema_str, compat_level)
            if result["status"] == "error" or result.get("error"):
                overall_ok = False
            results.append(result)

    return {"results": results, "success": overall_ok}


async def _register_one_subject(
    client: httpx.AsyncClient,
    base: str,
    subject: str,
    schema_str: str,
    compat_level: str | None,
) -> dict[str, Any]:
    """One subject's worth of work: probe → maybe skip → maybe POST →
    set compatibility. Always returns a fully shaped result dict; never
    raises, so the outer loop can keep going on per-subject failures."""
    pre_id: int | None = None
    pre_version: int | None = None
    pre_schema_str: str | None = None
    try:
        latest_resp = await client.get(f"{base}/subjects/{subject}/versions/latest")
        if latest_resp.status_code == 200:
            body = latest_resp.json()
            pre_id = body.get("id")
            pre_version = body.get("version")
            pre_schema_str = body.get("schema")
        elif latest_resp.status_code != 404:
            latest_resp.raise_for_status()
    except Exception as exc:
        return {
            "subject": subject, "status": "error", "schema_id": None,
            "version": None, "previous_version": None, "compatibility": None,
            "error": f"latest probe failed: {exc}",
        }

    # Skip path: registered version's schema content already matches.
    if pre_schema_str is not None and _canonical_avro(pre_schema_str) == _canonical_avro(schema_str):
        applied_compat, compat_error = await _maybe_set_compat(client, base, subject, compat_level)
        return {
            "subject": subject, "status": "skipped", "schema_id": pre_id,
            "version": pre_version, "previous_version": pre_version,
            "compatibility": applied_compat, "error": compat_error,
        }

    # POST a new (or first-ever) version.
    try:
        post_resp = await client.post(
            f"{base}/subjects/{subject}/versions",
            json={"schema": schema_str, "schemaType": "AVRO"},
        )
        post_resp.raise_for_status()
        new_id = post_resp.json().get("id")
    except Exception as exc:
        return {
            "subject": subject, "status": "error", "schema_id": None,
            "version": None, "previous_version": pre_version,
            "compatibility": None, "error": f"register failed: {exc}",
        }

    # Re-probe for the resulting version number. Non-fatal on failure —
    # we still have the schema_id from the POST response.
    post_version: int | None = None
    try:
        latest2 = await client.get(f"{base}/subjects/{subject}/versions/latest")
        if latest2.status_code == 200:
            post_version = latest2.json().get("version")
    except Exception:
        pass

    status = "updated" if pre_id is not None else "registered"
    applied_compat, compat_error = await _maybe_set_compat(client, base, subject, compat_level)
    return {
        "subject": subject,
        "status": status,
        "schema_id": new_id,
        "version": post_version,
        "previous_version": pre_version,
        "compatibility": applied_compat,
        "error": compat_error,
    }


async def _maybe_set_compat(
    client: httpx.AsyncClient,
    base: str,
    subject: str,
    compat_level: str | None,
) -> tuple[str | None, str | None]:
    if not compat_level:
        return None, None
    try:
        resp = await client.put(
            f"{base}/config/{subject}",
            json={"compatibility": compat_level},
        )
        resp.raise_for_status()
        return compat_level, None
    except Exception as exc:
        return None, f"compatibility {compat_level} not set: {exc}"


# ──────────── Stream Output info (for the Stream Output settings tab) ────────────


_DEFAULT_TOPICS = {
    "raw":        "audit.raw.v1",
    "normalized": "audit.normalized.v1",
    "enriched":   "audit.enriched.v1",
    "denials":    "audit.signals.denials.v1",
    "highrisk":   "audit.signals.highrisk.v1",
    "alerts":     "audit.alerts.v1",
    "dlq":        "audit.dlq.v1",
}
_TOPIC_ENV_VARS = {
    "raw":        "AUDIT_RAW_TOPIC",
    "normalized": "AUDIT_NORMALIZED_TOPIC",
    "enriched":   "AUDIT_ENRICHED_TOPIC",
    "denials":    "AUDIT_SIGNALS_DENIALS_TOPIC",
    "highrisk":   "AUDIT_SIGNALS_HIGHRISK_TOPIC",
    "alerts":     "AUDIT_ALERTS_TOPIC",
    "dlq":        "DLQ_TOPIC",
}


@router.get("/settings/stream_output/info")
async def stream_output_info(
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregated read-only view used by the Stream Output settings tab.
    Returns:
      - the topic names AuditLens publishes to (resolved from env or defaults)
      - SR configured + whether audit.enriched.v1-value is registered (Avro vs JSON)
      - Confluent env/cluster ids + a deep-link to the Flink workspace
    """
    topics = {
        key: os.environ.get(env_var, default)
        for key, (env_var, default) in (
            (k, (_TOPIC_ENV_VARS[k], _DEFAULT_TOPICS[k])) for k in _DEFAULT_TOPICS
        )
    }

    url, api_key, api_secret = _get_sr_creds(db)
    sr_configured = bool(url)
    enriched_subject = f"{topics['enriched']}-value"
    enriched_avro_ready = False
    sr_error: str | None = None

    if sr_configured:
        base = _sr_base(url)
        auth = _sr_auth(api_key, api_secret)
        try:
            async with httpx.AsyncClient(auth=auth, timeout=_SR_TIMEOUT_SECONDS) as client:
                resp = await client.get(f"{base}/subjects/{enriched_subject}/versions/latest")
                if resp.status_code == 200:
                    enriched_avro_ready = True
                elif resp.status_code != 404:
                    sr_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            sr_error = str(exc)

    env_id = os.environ.get("CONFLUENT_ENV_ID", "")
    cluster_id = os.environ.get("CONFLUENT_CLUSTER_ID", "")
    flink_workspace_url = (
        f"https://confluent.cloud/environments/{env_id}/flink"
        if env_id else None
    )

    return {
        "topics": topics,
        "enriched_subject": enriched_subject,
        "schema_registry": {
            "configured": sr_configured,
            "url": url or None,
            "enriched_avro_ready": enriched_avro_ready,
            "error": sr_error,
        },
        "confluent": {
            "env_id": env_id or None,
            "cluster_id": cluster_id or None,
            "flink_workspace_url": flink_workspace_url,
        },
    }
