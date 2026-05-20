"""Tableflow export endpoints — status, enable, disable for audit.enriched.v1.

Only available for AWS and Azure clusters. GCP is hard-blocked by Confluent.
Requires CONFLUENT_CLUSTER_ID and CONFLUENT_ENV_ID env vars in addition to
the standard CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.routes.patterns import _require_admin
from backend.app.api.routes.settings import _get_sr_creds
from backend.app.core.config import get_settings
from backend.app.db.database import get_db

logger = logging.getLogger("auditlens.backend.tableflow")

router = APIRouter(tags=["tableflow"])

_TIMEOUT = 15.0
_AUDIT_TOPIC = "audit.enriched.v1"
_SCHEMA_SUBJECT = f"{_AUDIT_TOPIC}-value"
# tableflow.py lives at backend/app/api/routes/tableflow.py; the schemas
# directory sits at the repo root, so it is parents[4] from this file.
# Override via AUDITLENS_SCHEMA_DIR for tests/non-standard layouts.
_SCHEMA_FILE = Path(
    os.getenv(
        "AUDITLENS_SCHEMA_DIR",
        str(Path(__file__).resolve().parents[4] / "schemas"),
    )
) / "audit.enriched.v1.json"


def _confluent_base() -> str:
    return get_settings().confluent_api_base_url


def _require_creds() -> tuple[str, str]:
    s = get_settings()
    key = s.confluent_cloud_api_key or s.confluent_api_key
    secret = s.confluent_cloud_api_secret or s.confluent_api_secret
    if not key or not secret:
        raise HTTPException(
            status_code=400,
            detail="CONFLUENT_CLOUD_API_KEY and CONFLUENT_CLOUD_API_SECRET must be set",
        )
    return key, secret


def _cluster_context() -> tuple[str, str, str]:
    cluster_id = os.getenv("CONFLUENT_CLUSTER_ID", "")
    env_id = os.getenv("CONFLUENT_ENV_ID", "")
    cluster_cloud = (os.getenv("CONFLUENT_CLUSTER_CLOUD") or "").lower()
    return cluster_id, env_id, cluster_cloud


async def _maybe_register_schema(db: Session) -> dict[str, Any]:
    """Best-effort: register schemas/audit.enriched.v1.json with Schema
    Registry under the {topic}-value subject before enabling Tableflow.

    Returns a result dict with at least {'status': 'ok'|'skipped'|'error', ...}
    The caller treats failure as a warning, never a hard block — Tableflow
    enable proceeds regardless. (Per the agreed policy for SR hiccups.)
    """
    sr_url, sr_key, sr_secret = _get_sr_creds(db)
    if not sr_url:
        return {"status": "skipped", "reason": "SCHEMA_REGISTRY_URL not configured"}
    if not _SCHEMA_FILE.is_file():
        return {"status": "error", "reason": f"schema file not found at {_SCHEMA_FILE}"}
    try:
        schema_text = _SCHEMA_FILE.read_text(encoding="utf-8")
        # Validate it parses — bad JSON would fail downstream with a less clear error.
        json.loads(schema_text)
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "reason": f"could not read schema file: {exc}"}
    body = {"schemaType": "JSON", "schema": schema_text}
    auth = (sr_key, sr_secret) if (sr_key and sr_secret) else None
    url = f"{sr_url.rstrip('/')}/subjects/{_SCHEMA_SUBJECT}/versions"
    try:
        async with httpx.AsyncClient(auth=auth, timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                content=json.dumps(body),
                headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            )
    except Exception as exc:
        logger.warning("Schema Registry POST failed for %s: %s", _SCHEMA_SUBJECT, exc)
        return {"status": "error", "reason": f"request failed: {exc}"}
    if not resp.is_success:
        logger.warning(
            "Schema Registry returned %s for %s: %s",
            resp.status_code, _SCHEMA_SUBJECT, resp.text[:300],
        )
        return {
            "status": "error",
            "reason": f"HTTP {resp.status_code}: {resp.text[:300]}",
        }
    try:
        payload = resp.json()
        schema_id = payload.get("id")
    except (ValueError, AttributeError):
        schema_id = None
    logger.info("Schema registered: %s (id=%s)", _SCHEMA_SUBJECT, schema_id)
    return {"status": "ok", "subject": _SCHEMA_SUBJECT, "schema_id": schema_id}


class EnableTableflowRequest(BaseModel):
    format: str  # "iceberg" | "delta"
    storage_type: str  # "managed" | "custom"
    storage_bucket: str | None = None


_TABLEFLOW_DOCS_URL = "https://docs.confluent.io/cloud/current/topics/tableflow/overview.html"
# Per Confluent docs: Tableflow requires one of these cluster kinds. Basic /
# Standard clusters are explicitly not supported.
_SUPPORTED_CLUSTER_KINDS = {"Dedicated", "Enterprise", "Freight"}
# AWS + Azure only. GCP is excluded; this also gates the per-region check
# because Tableflow's region eligibility tracks the supported clouds.
_SUPPORTED_CLOUDS = {"aws", "azure"}


@router.get("/tableflow/prerequisites")
async def tableflow_prerequisites(
    request: Request,
    _auth: None = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Check the Confluent-side prerequisites for Tableflow before exposing
    the enable / configure form. Pure read — never calls /tableflow/* APIs,
    so it works on clusters where Tableflow itself is unreachable.

    Response shape:
        creds_missing: bool — CC API key / cluster context not set
        api_error: str|None — CC /cmk lookup failed (we treat as soft-degrade)
        all_passed: bool
        prerequisites: { cluster_type, cloud_provider, schema_registry, region }
            each = { ok: bool, value: str, message: str }
        docs_url: str
    """
    s = get_settings()
    key = s.confluent_cloud_api_key or s.confluent_api_key
    secret = s.confluent_cloud_api_secret or s.confluent_api_secret
    cluster_id, env_id, _ = _cluster_context()

    if not (key and secret and cluster_id and env_id):
        return {
            "creds_missing": True,
            "all_passed": False,
            "prerequisites": {},
            "docs_url": _TABLEFLOW_DOCS_URL,
            "message": (
                "Set CONFLUENT_CLOUD_API_KEY, CONFLUENT_CLOUD_API_SECRET, "
                "CONFLUENT_CLUSTER_ID, and CONFLUENT_ENV_ID to enable "
                "automatic prerequisite checking."
            ),
        }

    cluster_kind: str | None = None
    cluster_cloud: str | None = None
    cluster_region: str | None = None
    api_error: str | None = None
    try:
        async with httpx.AsyncClient(auth=(key, secret), timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_confluent_base()}/cmk/v2/clusters/{cluster_id}",
                params={"environment": env_id},
            )
        if resp.is_success:
            data = resp.json() or {}
            spec = data.get("spec") or {}
            cluster_kind = ((spec.get("config") or {}).get("kind") or "").strip() or None
            cluster_cloud = (spec.get("cloud") or "").lower() or None
            cluster_region = spec.get("region") or None
        else:
            api_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        api_error = f"{exc.__class__.__name__}: {exc}"

    if api_error:
        return {
            "creds_missing": False,
            "all_passed": False,
            "api_error": api_error,
            "prerequisites": {},
            "docs_url": _TABLEFLOW_DOCS_URL,
        }

    sr_url, _sr_key, _sr_secret = _get_sr_creds(db)

    kind_ok = cluster_kind in _SUPPORTED_CLUSTER_KINDS
    cloud_ok = (cluster_cloud or "") in _SUPPORTED_CLOUDS
    sr_ok = bool(sr_url)
    # Region check follows cloud eligibility: AWS = all Flink regions, Azure
    # GA, GCP = unsupported. We don't ship a region allow-list because it
    # changes faster than this code does.
    region_ok = cloud_ok and bool(cluster_region)

    prerequisites = {
        "cluster_type": {
            "ok": kind_ok,
            "value": cluster_kind or "unknown",
            "message": (
                f"{cluster_kind} (supported)"
                if kind_ok
                else (
                    f"{cluster_kind or 'unknown'} — Tableflow requires Dedicated, "
                    "Enterprise, or Freight (Basic / Standard are not supported)."
                )
            ),
        },
        "cloud_provider": {
            "ok": cloud_ok,
            "value": cluster_cloud or "unknown",
            "message": (
                f"{(cluster_cloud or '').upper()} (supported)"
                if cloud_ok
                else (
                    f"{(cluster_cloud or 'unknown').upper()} — Tableflow is AWS "
                    "and Azure only (GCP not supported)."
                )
            ),
        },
        "schema_registry": {
            "ok": sr_ok,
            "value": "configured" if sr_ok else "not configured",
            "message": (
                "configured"
                if sr_ok
                else "Schema Registry must be enabled (Tableflow does not support schemaless topics)."
            ),
        },
        "region": {
            "ok": region_ok,
            "value": cluster_region or "unknown",
            "message": (
                f"{cluster_region} (supported)"
                if region_ok
                else f"{cluster_region or 'unknown'} — region eligibility follows the cloud provider."
            ),
        },
    }

    return {
        "creds_missing": False,
        "all_passed": all(p["ok"] for p in prerequisites.values()),
        "prerequisites": prerequisites,
        "docs_url": _TABLEFLOW_DOCS_URL,
    }


@router.get("/tableflow/status")
async def tableflow_status(request: Request, _auth: None = Depends(_require_admin)) -> dict[str, Any]:
    key, secret = _require_creds()
    cluster_id, env_id, cluster_cloud = _cluster_context()

    eligible = cluster_cloud in ("aws", "azure")
    ineligible_reason = (
        "GCP clusters are not supported by Tableflow" if cluster_cloud == "gcp" else None
    )

    try:
        async with httpx.AsyncClient(auth=(key, secret), timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_confluent_base()}/tableflow/v1/topics",
                params={"cluster_id": cluster_id, "environment_id": env_id},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Confluent API error: {exc}")

    base_response = {
        "topic": _AUDIT_TOPIC,
        "cluster_cloud": cluster_cloud,
        "eligible": eligible,
        "ineligible_reason": ineligible_reason,
    }

    if not resp.is_success:
        return {**base_response, "enabled": False, "format": None, "storage": None}

    topics = resp.json().get("data") or []
    match = next((t for t in topics if t.get("topic_name") == _AUDIT_TOPIC), None)
    if not match:
        return {**base_response, "enabled": False, "format": None, "storage": None}

    spec = match.get("spec", {})
    formats = spec.get("table_formats") or []
    fmt = (formats[0].get("format") or "").lower() if formats else None
    storage_spec = spec.get("storage") or {}
    storage_type = "custom" if storage_spec.get("provider") else "managed"

    return {**base_response, "enabled": True, "format": fmt, "storage": storage_type}


@router.post("/tableflow/enable")
async def tableflow_enable(
    body: EnableTableflowRequest,
    request: Request,
    _auth: None = Depends(_require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    key, secret = _require_creds()
    cluster_id, env_id, cluster_cloud = _cluster_context()

    if cluster_cloud == "gcp":
        raise HTTPException(status_code=400, detail="Tableflow not available on GCP")
    if body.format == "delta" and body.storage_type != "custom":
        raise HTTPException(status_code=400, detail="Delta Lake format requires storage_type=custom")
    if body.storage_type == "custom" and not body.storage_bucket:
        raise HTTPException(status_code=400, detail="storage_bucket required when storage_type=custom")

    # Best-effort schema registration. Per policy: SR failures degrade to a
    # warning in the response, never block the Tableflow enable.
    schema_registration = await _maybe_register_schema(db)

    bucket = body.storage_bucket or ""
    if body.storage_type == "managed":
        storage_config: dict[str, Any] = {"type": "managed"}
    elif bucket.startswith("s3://"):
        storage_config = {"provider": "aws", "s3": {"bucket_uri": bucket}}
    elif bucket.startswith("abfss://"):
        storage_config = {"provider": "azure", "adls": {"path": bucket}}
    else:
        storage_config = {"provider": "custom", "uri": bucket}

    payload = {
        "topic_name": _AUDIT_TOPIC,
        "spec": {
            "cluster": {"id": cluster_id},
            "environment": {"id": env_id},
            "record_failure_strategy": "SUSPEND",
            "table_formats": [{"format": body.format.upper()}],
            "storage": storage_config,
        },
    }

    try:
        async with httpx.AsyncClient(auth=(key, secret), timeout=_TIMEOUT) as client:
            resp = await client.post(f"{_confluent_base()}/tableflow/v1/topics", json=payload)
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return {
            "enabled": True,
            "format": body.format,
            "schema_registration": schema_registration,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Confluent API error: {exc}")


@router.post("/tableflow/disable")
async def tableflow_disable(request: Request, _auth: None = Depends(_require_admin)) -> dict[str, Any]:
    key, secret = _require_creds()
    cluster_id, env_id, _ = _cluster_context()

    try:
        async with httpx.AsyncClient(auth=(key, secret), timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{_confluent_base()}/tableflow/v1/topics/{_AUDIT_TOPIC}",
                params={"cluster_id": cluster_id, "environment_id": env_id},
            )
        if not resp.is_success and resp.status_code != 404:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return {"disabled": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Confluent API error: {exc}")
