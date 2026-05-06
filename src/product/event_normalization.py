import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from src.product.event_intelligence import decision_snapshot
from src.product.actor_enrichment import enrich_actor
from src.product.source_enrichment import extract_source_info

RESOURCE_TYPE_ALIASES = {
    "topic": "topic",
    "topics": "topic",
    "subject": "subject",
    "schema": "subject",
    "schema_subject": "subject",
    "schema registry": "schema_registry",
    "schema_registry": "schema_registry",
    "schemaregistry": "schema_registry",
    "connector": "connector",
    "connect": "connector",
    "role_binding": "role_binding",
    "role binding": "role_binding",
    "rolebinding": "role_binding",
    "acl / rbac": "role_binding",
    "acl": "role_binding",
    "rbac": "role_binding",
    "environment": "environment",
    "env": "environment",
    "cluster": "cluster",
    "kafka_cluster": "cluster",
    "cloud_cluster": "cluster",
    "api key": "api_key",
    "api_key": "api_key",
    "apikey": "api_key",
    "compute pool": "compute_pool",
    "compute_pool": "compute_pool",
    "flink": "compute_pool",
    "statement": "statement",
    "flink_statement": "statement",
    "tableflow": "tableflow",
    "unknown": "unknown",
}

RESOURCE_TYPE_LABELS = {
    "topic": "Topic",
    "subject": "Subject",
    "schema_registry": "Schema Registry",
    "connector": "Connector",
    "role_binding": "Role Binding",
    "environment": "Environment",
    "cluster": "Cluster",
    "api_key": "API Key",
    "compute_pool": "Compute Pool",
    "statement": "Statement",
    "tableflow": "Tableflow",
    "unknown": "Unknown",
}


def canonical_resource_type(value: Any) -> str:
    text = _as_text(value).replace("-", "_").strip().lower()
    text = re.sub(r"[_\s]+", " ", text)
    return RESOURCE_TYPE_ALIASES.get(text, RESOURCE_TYPE_ALIASES.get(text.replace(" ", "_"), text.replace(" ", "_") or "unknown"))


def resource_type_label(value: Any) -> str:
    canonical = canonical_resource_type(value)
    return RESOURCE_TYPE_LABELS.get(canonical, canonical.replace("_", " ").title())


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
    text = _as_text(value).strip()
    if not text:
        return "-"
    if "/topic=" in text:
        return f"Topic: {_extract_crn_value(text, '/topic=')}"
    if text.lower().startswith("topic="):
        return f"Topic: {text.split('=', 1)[1].strip()}"
    if "/cloud-cluster=" in text:
        return f"Cluster: {_extract_crn_value(text, '/cloud-cluster=')}"
    if "/apikey=" in text:
        return f"API Key: {_extract_crn_value(text, '/apikey=')}"
    return text


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
    primary = _cloud_primary_resource(payload)
    if primary:
        resource_type = canonical_resource_type(primary["resource_type"])
        resource_name = primary["resource_name"]
        label = resource_type_label(resource_type)
        return {
            "resource_type": resource_type,
            "resource_name": resource_name,
            "resource_display": f"{label}: {resource_name}",
            "raw_resource": resource_name,
        }
    fields = (
        "resourceName",
        "authzResourceName",
        "resource_name",
        "resource_display",
        "summary",
        "message",
        "request",
        "requestData",
        "request_data",
        "topic_name",
        "cluster_id",
    )
    raw_resource = _as_text(_first_present(payload, fields, ""))
    search_text = " ".join(
        _as_text(payload.get(field))
        for field in (
            *fields,
            "methodName",
            "method_name",
            "resourceType",
            "resource_type",
            "action",
        )
    )
    lowered = search_text.lower()
    resource_type_hint = _as_text(payload.get("resourceType") or payload.get("resource_type"))

    marker_types = (
        ("/topic=", "Topic"),
        ("/cloud-cluster=", "Cluster"),
        ("/schema-registry=", "Schema Registry"),
        ("/ksql=", "KSQL"),
        ("/compute-pool=", "Compute Pool"),
        ("/apikey=", "API Key"),
    )
    resource_type = "Unknown"
    resource_name = "-"

    for marker, label in marker_types:
        source = next((_as_text(payload.get(field)) for field in fields if marker in _as_text(payload.get(field))), "")
        if source:
            resource_type = canonical_resource_type(label)
            resource_name = _extract_crn_value(source, marker)
            break

    if resource_type == "Unknown":
        if payload.get("topic_name"):
            resource_type = "topic"
            resource_name = _as_text(payload.get("topic_name"))
        elif "topic" in lowered:
            resource_type = "topic"
            quoted_topic = _extract_quoted_topic(search_text)
            if quoted_topic:
                resource_name = quoted_topic
        elif resource_type_hint:
            resource_type = canonical_resource_type(resource_type_hint)
        elif any(marker in lowered for marker in ("subject=", "/subject=", "schema subject")):
            resource_type = "subject"
        elif "connector" in lowered:
            resource_type = "connector"
        elif "apikey" in lowered or "api key" in lowered:
            resource_type = "api_key"
        elif any(marker in lowered for marker in ("createacl", "deleteacl", "acl:", "/acl=", " rbac", "rolebinding", "role binding")):
            resource_type = "role_binding"
        elif "environment" in lowered or "/environment=" in lowered:
            resource_type = "environment"
        elif "tableflow" in lowered:
            resource_type = "tableflow"
        elif "cluster" in lowered or resource_type_hint.upper() in {"CLUSTER", "KAFKA_CLUSTER"}:
            resource_type = "cluster"

    if resource_name == "-":
        quoted_topic = _extract_quoted_topic(search_text)
        if resource_type == "topic" and quoted_topic:
            resource_name = quoted_topic
        elif raw_resource:
            resource_name = summarize_resource(raw_resource)
            if ":" in resource_name:
                resource_name = resource_name.split(":", 1)[1].strip()
        elif payload.get("cluster_id"):
            resource_name = _as_text(payload.get("cluster_id"))

    if resource_type in {"connector", "api_key", "role_binding"} and resource_name == "-":
        resource_name = summarize_resource(raw_resource) if raw_resource else resource_type_label(resource_type)

    resource_type = canonical_resource_type(resource_type)
    label = resource_type_label(resource_type)
    resource_display = f"{label}: {resource_name}" if resource_type != "unknown" and resource_name != "-" else summarize_resource(raw_resource)
    return {
        "resource_type": resource_type,
        "resource_name": resource_name or "-",
        "resource_display": resource_display or "Unknown",
        "raw_resource": raw_resource or "-",
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
    resource_info = derive_resource_info(payload)
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
        "cluster_id": _as_text(payload.get("cluster_id") or payload.get("clusterId")) or None,
        "source_ip": source_info["source_ip"],
        "source_context": source_info["source_context"],
        "client_id": source_info["client_id"],
        "connection_id": source_info["connection_id"],
        "request_id": source_info["request_id"],
        "environment_id": source_info["environment_id"],
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
