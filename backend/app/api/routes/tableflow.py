"""Tableflow export endpoints — status, enable, disable for audit.enriched.v1.

Only available for AWS and Azure clusters. GCP is hard-blocked by Confluent.
Requires CONFLUENT_CLUSTER_ID and CONFLUENT_ENV_ID env vars in addition to
the standard CONFLUENT_CLOUD_API_KEY / CONFLUENT_CLOUD_API_SECRET.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.app.api.routes.patterns import _require_admin

router = APIRouter(tags=["tableflow"])

_TIMEOUT = 15.0
_AUDIT_TOPIC = "audit.enriched.v1"


def _confluent_base() -> str:
    return os.getenv("CONFLUENT_API_BASE_URL", "https://api.confluent.cloud")


def _require_creds() -> tuple[str, str]:
    key = os.getenv("CONFLUENT_CLOUD_API_KEY") or os.getenv("CONFLUENT_API_KEY") or ""
    secret = os.getenv("CONFLUENT_CLOUD_API_SECRET") or os.getenv("CONFLUENT_API_SECRET") or ""
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


class EnableTableflowRequest(BaseModel):
    format: str  # "iceberg" | "delta"
    storage_type: str  # "managed" | "custom"
    storage_bucket: str | None = None


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
async def tableflow_enable(body: EnableTableflowRequest, request: Request, _auth: None = Depends(_require_admin)) -> dict[str, Any]:
    key, secret = _require_creds()
    cluster_id, env_id, cluster_cloud = _cluster_context()

    if cluster_cloud == "gcp":
        raise HTTPException(status_code=400, detail="Tableflow not available on GCP")
    if body.format == "delta" and body.storage_type != "custom":
        raise HTTPException(status_code=400, detail="Delta Lake format requires storage_type=custom")
    if body.storage_type == "custom" and not body.storage_bucket:
        raise HTTPException(status_code=400, detail="storage_bucket required when storage_type=custom")

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
        return {"enabled": True, "format": body.format}
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
