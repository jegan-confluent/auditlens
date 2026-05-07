import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from src.product.event_intelligence import decision_snapshot
from src.product.actor_enrichment import enrich_actor
from src.product.resource_intelligence import (
    canonical_resource_type as _canonical_resource_type,
    extract_resource_context,
    resource_type_label as _resource_type_label,
    summarize_resource as _summarize_resource,
)
from src.product.source_enrichment import extract_source_info


def canonical_resource_type(value: Any) -> str:
    return _canonical_resource_type(value)


def resource_type_label(value: Any) -> str:
    return _resource_type_label(value)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _first_present(payload: dict[str, Any], fields: tuple[str, ...], default: Any = "") -> Any:
    for field in fields:
        value = payload.get(field)
        if value not in (None, ""):
            return value
    return default


def _extract_crn_value(text: str, marker: str) -> str:
    if marker not in text:
        return "-"
    tail = text.split(marker, 1)[1]
    for separator in ("/", ":", " "):
        if separator in tail:
            tail = tail.split(separator, 1)[0]
    return tail.strip("'\" ") or "-"


def _extract_quoted_topic(text: str) -> str:
    match = re.search(r"topic\s+['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _load_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return _load_json(payload.get("data_json"))


def _cloud_resources(payload: dict[str, Any]) -> dict[str, Any]:
    data = _data(payload)
    value = payload.get("cloudResources") or data.get("cloudResources")
    if isinstance(value, dict):
        return value
    return _load_json(value)


def _cloud_primary_resource(payload: dict[str, Any]) -> dict[str, str] | None:
    resources = _cloud_resources(payload)
    resource = resources.get("resource")
    if not isinstance(resource, dict):
        return None
    resource_type = _as_text(resource.get("resourceType") or resource.get("type"))
    resource_id = _as_text(resource.get("resourceId") or resource.get("id") or resource.get("name"))
    if not resource_type or not resource_id:
        return None
    return {"resource_type": resource_type, "resource_name": resource_id}


def summarize_resource(value: Any) -> str:
    return _summarize_resource(value)


def derive_action_category(method_name: str | None, action: str | None) -> str:
    method = str(method_name or "")
    action_text = str(action or "")
    combined = f"{method} {action_text}"
    lowered = re.sub(r"[_./-]+", " ", combined).lower()
    compact = re.sub(r"[^a-z0-9]+", "", lowered)

    if "apikey" in compact or "api key" in lowered:
        return "API Key"
    if any(marker in compact for marker in ("createacl", "createacls", "deleteacl", "deleteacls", "rolebinding", "rbac")) or re.search(r"\bacl\b", lowered):
        return "Security"
    if "createtopic" in compact or "createtopics" in compact:
        return "Create"
    if "deletetopic" in compact or "deletetopics" in compact:
        return "Delete"
    if any(marker in compact for marker in ("getstatement", "liststatements", "tableflowgettable", "produce", "fetch", "consume", "read")):
        return "Data"
    if any(marker in compact for marker in ("authorize", "authorization", "authentication", "authenticate")):
        return "Security"
    if "delete" in compact:
        return "Delete"
    if any(marker in compact for marker in ("updatestatement", "patchstatement", "alter", "update", "modify", "config")):
        return "Modify"
    if "create" in compact:
        return "Create"
    return "Other"


def humanize_action(payload: dict[str, Any]) -> str:
    method = _as_text(payload.get("methodName") or payload.get("method_name"))
    action = _as_text(payload.get("action"))
    lowered = f"{method} {action}".lower()

    if "authentication" in lowered or "authenticate" in lowered:
        return "Kafka authentication"
    if "authorize" in lowered:
        return "Authorize"
    if "createacl" in lowered or "createacls" in lowered:
        return "Create ACL"
    if "deleteacl" in lowered or "deleteacls" in lowered:
        return "Delete ACL"
    if "createtopic" in lowered or "createtopics" in lowered:
        return "Create topic"
    if "deletetopic" in lowered or "deletetopics" in lowered:
        return "Delete topic"
    if "tableflowgettable" in lowered:
        return "Tableflow get table"
    if "getstatement" in lowered or "liststatements" in lowered:
        return "Read/listed"
    if "createstatement" in lowered:
        return "Create statement"
    if "deletestatement" in lowered:
        return "Delete statement"
    if "updatestatement" in lowered or "patchstatement" in lowered:
        return "Update statement"
    if "fetch" in lowered:
        return "Fetch"
    return (action or method or "-").replace("_", " ").strip()


def derive_resource_info(payload: dict[str, Any]) -> dict[str, str]:
    context = extract_resource_context(payload)
    return {
        "resource_type": context.resource_type,
        "resource_name": context.resource_name,
        "resource_display": context.resource_display_name,
        "raw_resource": context.raw_resource,
    }


def is_denied(payload: dict[str, Any]) -> bool:
    result = _as_text(payload.get("resultStatus") or payload.get("result") or payload.get("result_display")).lower()
    return "denied" in result or payload.get("granted") is False


def is_failure(payload: dict[str, Any]) -> bool:
    result = _as_text(payload.get("resultStatus") or payload.get("result") or payload.get("result_display")).lower()
    return bool(payload.get("is_failure")) or is_denied(payload) or any(
        marker in result for marker in ("error", "fail", "denied", "unauthorized", "forbidden", "not_found", "not found", "404")
    )


def is_routine_noise(payload: dict[str, Any], action_category: str) -> bool:
    if action_category in {"Create", "Delete", "Modify", "API Key"} or is_failure(payload) or is_denied(payload):
        return False
    text = f"{_as_text(payload.get('methodName') or payload.get('method_name'))} {_as_text(payload.get('action'))}".lower()
    return any(marker in text for marker in ("authentication", "authenticate", "authorize", "metadata", "fetch", "getkafkaclusters", "listcomputepools"))


def parse_event_timestamp(payload: dict[str, Any]) -> datetime:
    timestamp = payload.get("timestamp") or payload.get("time") or payload.get("event_time")
    if isinstance(timestamp, datetime):
        return timestamp
    if isinstance(timestamp, str) and timestamp:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def normalize_event(payload: dict[str, Any]) -> dict[str, Any]:
    method = _as_text(payload.get("methodName") or payload.get("method_name"))
    action = _as_text(payload.get("action"))
    action_category = derive_action_category(method, action)
    resource_context = extract_resource_context(payload)
    resource_info = {
        "resource_type": resource_context.resource_type,
        "resource_name": resource_context.resource_name,
        "resource_display": resource_context.resource_display_name,
        "raw_resource": resource_context.raw_resource,
    }
    failure = is_failure(payload)
    denied = is_denied(payload)
    result = "Failure" if failure else "Success"
    actor = _as_text(_first_present(payload, ("user_display", "user", "principal", "actor"), "Unknown actor")) or "Unknown actor"
    actor_info = enrich_actor(actor)
    source_info = extract_source_info(payload)
    decision = decision_snapshot(payload)
    summary = _as_text(payload.get("summary") or payload.get("message"))
    if not summary:
        summary = f"{actor} {humanize_action(payload)} {resource_info['resource_display']}".strip()
    return {
        "result": result,
        "actor": actor,
        "actor_id": actor_info["actor_id"],
        "actor_display_name": actor_info["actor_display_name"],
        "actor_email": actor_info["actor_email"],
        "actor_type": actor_info["actor_type"],
        "actor_source": actor_info["actor_source"],
        "actor_confidence": actor_info["actor_confidence"],
        "actor_enriched_at": actor_info["actor_enriched_at"],
        "action": action or method,
        "normalized_action": humanize_action(payload),
        "action_category": action_category,
        "resource_type": resource_info["resource_type"],
        "resource_name": resource_info["resource_name"],
        "resource_display": resource_info["resource_display"],
        "resource_display_name": resource_context.resource_display_name,
        "cluster_id": _as_text(payload.get("cluster_id") or payload.get("clusterId")) or None,
        "cluster_name": resource_context.cluster_name,
        "source_ip": source_info["source_ip"],
        "source_context": source_info["source_context"],
        "client_id": source_info["client_id"],
        "connection_id": source_info["connection_id"],
        "request_id": source_info["request_id"],
        "environment_id": source_info["environment_id"],
        "environment_name": resource_context.environment_name,
        "parent_resource": resource_context.parent_resource,
        "resource_scope": resource_context.resource_scope,
        "resource_criticality": resource_context.resource_criticality,
        "blast_radius_hint": resource_context.blast_radius_hint,
        "production_hint": resource_context.production_hint,
        "flink_region": source_info["flink_region"],
        "network_id": source_info["network_id"],
        "summary": summary,
        "is_failure": failure,
        "is_denied": denied,
        "is_routine_noise": is_routine_noise(payload, action_category),
        "signal_type": decision["signal_type"],
        "signal_reason": decision["signal_reason"],
        "impact_type": decision["impact_type"],
        "risk_level": decision["risk_level"],
        "change_type": decision["change_type"],
        "resource_family": decision["resource_family"],
        "event_title": decision["event_title"],
        "event_summary": decision["event_summary"],
        "decision_reason": decision["decision_reason"],
        "decision_label": decision["decision_label"],
        "recommended_action": decision["recommended_action"],
    }


def event_fingerprint(payload: dict[str, Any]) -> str:
    for field in ("id", "event_id", "eventId", "requestId", "correlation_id", "correlationId"):
        value = payload.get(field)
        if value not in (None, ""):
            return hashlib.sha256(f"{field}:{value}".encode("utf-8")).hexdigest()
    normalized = normalize_event(payload)
    timestamp_value = payload.get("timestamp") or payload.get("time") or payload.get("event_time")
    stable = {
        "actor": normalized["actor"],
        "action": normalized["action"],
        "cluster_id": normalized["cluster_id"],
        "resource_type": normalized["resource_type"],
        "resource_name": normalized["resource_name"],
        "summary": normalized["summary"],
        "source_topic": _first_present(payload, ("source_topic", "topic"), None),
        "source_partition": _first_present(payload, ("source_partition", "partition"), None),
        "source_offset": _first_present(payload, ("source_offset", "offset"), None),
    }
    if timestamp_value not in (None, ""):
        stable["timestamp"] = parse_event_timestamp(payload).isoformat()
    else:
        stable["raw_payload"] = payload
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()
