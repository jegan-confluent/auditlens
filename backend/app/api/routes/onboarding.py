"""Onboarding wizard endpoints — discover environments/clusters, validate bootstrap."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.app.core.limiter import limiter

router = APIRouter(tags=["onboarding"])

_TIMEOUT = 15.0


def _confluent_base() -> str:
    return os.getenv("CONFLUENT_API_BASE_URL", "https://api.confluent.cloud")


class DiscoverRequest(BaseModel):
    api_key: str
    api_secret: str


class ValidateClusterRequest(BaseModel):
    bootstrap: str
    api_key: str
    api_secret: str


@router.post("/onboarding/discover")
@limiter.limit("5/minute")
async def discover(request: Request, body: DiscoverRequest) -> dict[str, Any]:
    base = _confluent_base()
    auth = (body.api_key, body.api_secret)

    async with httpx.AsyncClient(auth=auth, timeout=_TIMEOUT) as client:
        try:
            envs_task = client.get(f"{base}/org/v2/environments")
            audit_task = client.get(f"{base}/audit-log/v1/config")
            envs_resp, audit_resp = await asyncio.gather(envs_task, audit_task, return_exceptions=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Confluent API error: {exc}")

    if isinstance(envs_resp, Exception):
        raise HTTPException(status_code=502, detail=f"Environments fetch failed: {envs_resp}")
    if isinstance(audit_resp, Exception):
        raise HTTPException(status_code=502, detail=f"Audit config fetch failed: {audit_resp}")

    if not envs_resp.is_success:
        raise HTTPException(status_code=envs_resp.status_code, detail=envs_resp.text)
    if not audit_resp.is_success:
        raise HTTPException(status_code=audit_resp.status_code, detail=audit_resp.text)

    environments_raw = (envs_resp.json().get("data") or [])[:10]

    environments: list[dict[str, Any]] = []
    total_clusters = 0
    audit_enabled_count = 0
    tableflow_eligible_count = 0

    async with httpx.AsyncClient(auth=auth, timeout=_TIMEOUT) as client:
        for env in environments_raw:
            env_id = env.get("id", "")
            env_name = env.get("display_name") or env.get("name") or env_id
            clusters: list[dict[str, Any]] = []
            schema_registry: dict[str, Any] | None = None
            try:
                cr = await client.get(
                    f"{base}/cmk/v2/clusters",
                    params={"environment": env_id, "page_size": 50},
                )
                if cr.is_success:
                    for c in cr.json().get("data") or []:
                        spec = c.get("spec", {})
                        cloud = (spec.get("cloud") or "").lower()
                        eligible = cloud in ("aws", "azure")
                        clusters.append({
                            "id": c.get("id", ""),
                            "name": spec.get("display_name") or c.get("id", ""),
                            "bootstrap": spec.get("kafka_bootstrap_endpoint", ""),
                            "cloud": cloud,
                            "region": spec.get("region", ""),
                            "audit_enabled": True,
                            "tableflow_eligible": eligible,
                        })
                        total_clusters += 1
                        audit_enabled_count += 1
                        if eligible:
                            tableflow_eligible_count += 1
            except Exception:
                pass
            try:
                sr_resp = await client.get(
                    f"{base}/srcm/v3/clusters",
                    params={"environment": env_id},
                )
                if sr_resp.is_success:
                    sr_data = (sr_resp.json().get("data") or [])
                    if sr_data:
                        sr = sr_data[0]
                        sr_spec = sr.get("spec", {})
                        schema_registry = {
                            "id": sr.get("id", ""),
                            "endpoint": sr_spec.get("http_endpoint", ""),
                            "package": sr_spec.get("package", ""),
                        }
            except Exception:
                pass
            environments.append({
                "id": env_id,
                "name": env_name,
                "clusters": clusters,
                "schema_registry": schema_registry,
            })

    return {
        "environments": environments,
        "total_clusters": total_clusters,
        "audit_enabled_count": audit_enabled_count,
        "tableflow_eligible_count": tableflow_eligible_count,
    }


@router.post("/onboarding/validate-cluster")
@limiter.limit("5/minute")
async def validate_cluster(request: Request, body: ValidateClusterRequest) -> dict[str, Any]:
    try:
        from confluent_kafka.admin import AdminClient  # type: ignore[import-untyped]

        admin = AdminClient({
            "bootstrap.servers": body.bootstrap,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "PLAIN",
            "sasl.username": body.api_key,
            "sasl.password": body.api_secret,
            "socket.timeout.ms": 10000,
        })
        import asyncio
        metadata = await asyncio.get_running_loop().run_in_executor(
            None, lambda: admin.list_topics(timeout=10)
        )
        audit_topic_exists = "confluent-audit-log-events" in metadata.topics
        return {"valid": True, "audit_topic_exists": audit_topic_exists}
    except ImportError:
        return {"valid": True, "audit_topic_exists": None, "note": "topic check skipped"}
    except Exception as exc:
        return {"valid": False, "error": str(exc), "audit_topic_exists": None}
