import json
import re
from datetime import datetime, timezone
from typing import Any

from src.product.source_enrichment import extract_source_info
from src.product.resource_intelligence import resource_display_short as resource_display_short_from_context


IMPACT_TYPES = {
    "constructive",
    "destructive",
    "configuration_change",
    "access_change",
    "authentication",
    "authorization_check",
    "read_only",
    "operational",
    "security_sensitive",
    "unknown",
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


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


def _payload_from_event(event: Any) -> dict[str, Any]:
    if hasattr(event, "__dict__") and "raw_payload_json" not in event.__dict__:
        return {}
    raw = getattr(event, "raw_payload_json", None)
    return _load_json(raw)


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return _load_json(payload.get("data_json"))


def _first(*values: Any) -> str:
    for value in values:
        text = _as_text(value).strip()
        if text:
            return text
    return ""


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _method(payload: dict[str, Any]) -> str:
    data = _data(payload)
    return _first(payload.get("methodName"), payload.get("method_name"), data.get("methodName"), payload.get("action"))


def _event_type(payload: dict[str, Any]) -> str:
    return _first(payload.get("type"), payload.get("event_type"))


def _result_text(payload: dict[str, Any]) -> str:
    data = _data(payload)
    return _first(
        payload.get("resultStatus"),
        payload.get("result"),
        payload.get("result_display"),
        data.get("result"),
        _nested(data, "authenticationInfo", "result"),
        _nested(data, "authorizationInfo", "result"),
    )


def _is_denied(payload: dict[str, Any], event: Any | None = None) -> bool:
    result = _result_text(payload).lower()
    return bool(getattr(event, "is_denied", False)) or payload.get("granted") is False or any(marker in result for marker in ("deny", "denied", "forbid", "unauthoriz"))


def _is_failure(payload: dict[str, Any], event: Any | None = None) -> bool:
    result = _result_text(payload).lower()
    return bool(getattr(event, "is_failure", False)) or _is_denied(payload, event) or any(
        marker in result for marker in ("fail", "error", "denied", "forbid", "unauthoriz", "not_found", "not found", "404")
    )


def _split_words(value: str) -> list[str]:
    compact = re.sub(r"[_./-]+", " ", value)
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", compact)
    return [word.lower() for word in re.findall(r"[A-Za-z0-9]+", expanded)]


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _change_type(method: str, event_type: str, denied: bool) -> str:
    words = _split_words(method)
    compact = _compact(method)
    if denied:
        return "denied"
    if "authentication" in event_type or "authenticate" in words or "authentication" in words:
        return "authenticated"
    if "authorization" in event_type or "authorize" in words or "authorization" in words:
        return "authorized"
    if any(word in words for word in ("delete", "deleted", "terminate", "destroy", "remove")):
        return "deleted"
    if any(word in words for word in ("create", "created", "invite", "provision")):
        return "created"
    if any(word in words for word in ("stop", "pause", "resume", "restore")):
        return "configured"
    if any(word in words for word in ("update", "updated", "alter", "patch", "set", "configure", "configured", "enable", "disable")) or "config" in compact:
        return "updated"
    if any(word in words for word in ("list", "get", "describe", "read", "fetch", "consume", "search")):
        return "read/listed"
    if any(word in words for word in ("produce", "write")):
        return "configured"
    return "unknown"


def _resource_family_from_text(value: str) -> str:
    text = value.lower()
    pairs = (
        ("schema_registry", ("schema", "schema-registry", "schema_registry")),
        ("tableflow", ("tableflow", "iceberg")),
        ("connector", ("connector", "connect")),
        ("service_account", ("serviceaccount", "service-account", "service account")),
        ("api_key", ("apikey", "api-key", "api key")),
        ("rbac", ("rolebinding", "role-binding", "rbac", "role binding")),
        # Word-boundary-safe markers: plain "acl" is a substring of
        # "kafkacluster" (kafk**acl**uster), causing false ACL matches on
        # CreateKafkaCluster. Use method-prefixed forms that won't match there.
        ("acl", ("createacl", "deleteacl", "describeacl", "listacl", " acl", "/acl=")),
        ("topic", ("topic",)),
        ("ksql", ("ksql",)),
        ("flink", ("flink", "compute-pool", "workspace", "statement")),
        ("cluster", ("cluster", "lkc-", "cloud-cluster")),
        ("environment", ("environment", "env-")),
        ("user", ("user", "identity")),
        ("network", ("network", "privatelink", "private-link")),
        ("billing", ("billing", "invoice", "payment")),
        ("organization", ("organization", "org")),
    )
    for family, markers in pairs:
        if any(marker in text for marker in markers):
            return family
    return "unknown"


def _resource_family(payload: dict[str, Any], event: Any | None = None) -> str:
    data = _data(payload)
    cloud_resources = data.get("cloudResources") if isinstance(data.get("cloudResources"), dict) else _load_json(data.get("cloudResources"))
    if not cloud_resources:
        cloud_resources = payload.get("cloudResources") if isinstance(payload.get("cloudResources"), dict) else _load_json(payload.get("cloudResources"))
    resource = cloud_resources.get("resource") if isinstance(cloud_resources, dict) else None
    if isinstance(resource, dict) and _first(resource.get("resourceType"), resource.get("type")).upper() == "STATEMENT":
        return "flink"
    existing = _first(getattr(event, "resource_type", ""), payload.get("resourceType"), payload.get("resource_type"))
    method = _method(payload)
    event_type = _event_type(payload)
    raw = _first(payload.get("resourceName"), payload.get("authzResourceName"), getattr(event, "resource_display", ""), getattr(event, "resource_name", ""))
    family = _resource_family_from_text(" ".join((existing, method, event_type, raw)))
    if family != "unknown":
        return family
    resources = _as_text(data.get("cloudResources"))
    return _resource_family_from_text(resources)


def _is_security_resource(family: str, method: str, event_type: str) -> bool:
    text = f"{family} {method} {event_type}".lower()
    return family in {"api_key", "acl", "rbac", "service_account", "user", "network", "organization"} or any(
        marker in text for marker in ("access-transparency", "role", "permission", "invite", "grant", "revoke", "apikey", "api key", "acl")
    )


def classify_event(payload: dict[str, Any], event: Any | None = None) -> dict[str, str]:
    method = _method(payload) or _as_text(getattr(event, "action", ""))
    event_type = _event_type(payload)
    denied = _is_denied(payload, event)
    failed = _is_failure(payload, event)
    change_type = _change_type(method, event_type, denied)
    family = _resource_family(payload, event)
    method_text = method.lower()
    event_type_text = event_type.lower()
    compact = _compact(method)

    if "access-transparency" in event_type_text:
        impact = "security_sensitive"
    elif denied:
        impact = "security_sensitive"
    elif "authorization" in event_type_text or "authorize" in method_text:
        impact = "authorization_check"
    elif "authentication" in event_type_text or "authenticate" in method_text or "authentication" in method_text:
        impact = "authentication"
    elif any(marker in compact for marker in ("grant", "revoke", "invite", "assign", "removerole", "rolebinding", "createapikey", "deleteapikey")):
        impact = "access_change"
    elif change_type == "deleted":
        impact = "destructive"
    elif change_type == "created":
        impact = "access_change" if _is_security_resource(family, method, event_type) else "constructive"
    elif change_type == "updated":
        impact = "access_change" if _is_security_resource(family, method, event_type) else "configuration_change"
    elif change_type == "configured":
        impact = "operational" if family == "flink" and any(marker in compact for marker in ("stopstatement", "pausestatement", "resumestatement")) else ("access_change" if _is_security_resource(family, method, event_type) else "configuration_change")
    elif change_type == "read/listed":
        impact = "read_only"
    elif any(marker in compact for marker in ("pause", "restore", "signin")):
        impact = "operational"
    else:
        impact = "unknown"

    if impact == "security_sensitive" and (denied or failed or "access-transparency" in event_type_text):
        risk = "high"
    elif impact == "destructive" and family in {"cluster", "environment", "organization", "schema_registry", "service_account", "user", "api_key", "rbac", "acl"}:
        risk = "critical"
    elif impact in {"destructive", "access_change"}:
        risk = "high"
    elif impact in {"configuration_change", "constructive"} and _is_security_resource(family, method, event_type):
        risk = "high"
    elif impact in {"configuration_change", "constructive", "security_sensitive"}:
        risk = "medium"
    elif impact in {"authentication", "authorization_check", "read_only", "operational"}:
        risk = "informational" if not failed else "medium"
    else:
        risk = "low"

    return {
        "impact_type": impact if impact in IMPACT_TYPES else "unknown",
        "risk_level": risk,
        "change_type": change_type,
        "resource_family": family,
    }


def _principal_from_data(data: dict[str, Any]) -> tuple[str, str]:
    principal = _nested(data, "authenticationInfo", "principal") or {}
    if not isinstance(principal, dict):
        return "", "unknown"
    user_id = _nested(principal, "confluentUser", "resourceId")
    service_account_id = _nested(principal, "serviceAccount", "resourceId")
    if service_account_id:
        return _as_text(service_account_id), "service_account"
    if user_id:
        return _as_text(user_id), "user"
    text = _as_text(principal)
    if "serviceAccount" in text:
        return text, "service_account"
    if text:
        return text, "user"
    return "", "unknown"


def extract_subject(payload: dict[str, Any], event: Any | None = None) -> tuple[str, str]:
    data = _data(payload)
    subject = _first(
        payload.get("email"),
        payload.get("user_email"),
        payload.get("user_display"),
        payload.get("user"),
        payload.get("principal"),
        payload.get("principal_raw"),
        payload.get("actor"),
        getattr(event, "actor", ""),
    )
    subject_type = _first(payload.get("principal_type"), payload.get("subject_type")).lower() or "unknown"
    if not subject:
        subject, subject_type = _principal_from_data(data)
    if subject_type not in {"user", "service_account"}:
        lowered = subject.lower()
        if "serviceaccount" in lowered or lowered.startswith("sa-") or "User:sa-" in subject:
            subject_type = "service_account"
        elif subject:
            subject_type = "user"
    return subject or "Unknown actor", subject_type


def _extract_crn_tail(value: str) -> str:
    text = value.strip()
    if not text:
        return "Unknown"
    markers = (
        "/topic=",
        "/connector=",
        "/custom-connector-plugin=",
        "/schema-registry=",
        "/ksql=",
        "/flink-region=",
        "/compute-pool=",
        "/statement=",
        "/cloud-cluster=",
        "/environment=",
        "/service-account=",
        "/user=",
        "/api-key=",
        "/apikey=",
        "/network=",
        "/organization=",
    )
    for marker in markers:
        if marker in text:
            tail = text.rsplit(marker, 1)[1]
            return re.split(r"[/:\s'\"]", tail, 1)[0] or "Unknown"
    if ":" in text and len(text) < 120:
        return text.split(":", 1)[1].strip() or text
    if text.startswith("crn://"):
        return text.rsplit("/", 1)[-1].replace("=", ": ", 1)
    return text if len(text) <= 96 else f"{text[:93]}..."


def resource_display_short(payload: dict[str, Any], event: Any | None = None) -> str:
    return resource_display_short_from_context(payload, event)


def source_context(payload: dict[str, Any], event: Any | None = None) -> str:
    source_info = extract_source_info(payload, event)
    context = _as_text(source_info.get("source_context")) or _first(
        getattr(event, "_source_context", ""),
        getattr(event, "environment_id", ""),
        getattr(event, "cluster_id", ""),
        getattr(event, "network_id", ""),
    )
    return context or "Not provided by audit event"


def decision_reason_for(classification: dict[str, str], title: str, *, failed: bool = False) -> str:
    impact = classification["impact_type"]
    change = classification["change_type"]
    family = classification["resource_family"].replace("_", " ")
    if failed and impact == "read_only":
        return "Failed read request. Review if expected or caused by stale/missing resource."
    if change == "denied" or impact == "security_sensitive":
        return "Authorization failure detected"
    if impact == "destructive":
        return f"Destructive operation: {family} deletion"
    if impact == "configuration_change":
        return "Configuration change detected"
    if impact == "access_change":
        return "Access change detected"
    if impact == "authentication":
        return "Routine authentication activity"
    if impact == "authorization_check":
        return "Routine authorization check"
    if impact == "read_only":
        return "Routine read activity"
    if change == "created":
        return f"Creation activity: {title.lower()}"
    return "Audit activity classified by deterministic rules"


def _title_for(change_type: str, impact: str, family: str, *, failed: bool = False) -> str:
    family_label = {
        "api_key": "API key",
        "schema_registry": "Schema Registry",
        "service_account": "Service account",
        "rbac": "Role binding",
        "acl": "ACL",
        "ksql": "ksqlDB",
        "flink": "Flink statement",
    }.get(family, family.replace("_", " ").title() if family != "unknown" else "Resource")
    if failed and impact == "read_only":
        return f"{family_label} read failed" if family != "unknown" else "Failed read request"
    if change_type == "denied":
        return "Authorization denied" if impact == "security_sensitive" else "Request denied"
    if impact == "authorization_check":
        return "Authorization denied" if change_type == "denied" else "Authorization check"
    if impact == "authentication":
        return "Authentication denied" if change_type == "denied" else "Authentication succeeded"
    if change_type == "created":
        return f"{family_label} created"
    if change_type == "deleted":
        return f"{family_label} deleted"
    if change_type in {"updated", "configured"}:
        return f"{family_label} configuration updated"
    if change_type == "read/listed":
        return f"{family_label} read/listed"
    return f"{family_label} event"


def event_digest(payload: dict[str, Any], event: Any | None = None) -> dict[str, str]:
    classification = classify_event(payload, event)
    subject, subject_type = extract_subject(payload, event)
    resource = resource_display_short(payload, event)
    source = source_context(payload, event)
    source_info = extract_source_info(payload, event)
    source_ip = _as_text(source_info.get("source_ip")) or _first(getattr(event, "source_ip", ""))
    method = _method(payload) or _as_text(getattr(event, "action", ""))
    failed = _is_failure(payload, event)
    title = _title_for(classification["change_type"], classification["impact_type"], classification["resource_family"], failed=failed)
    decision_reason = decision_reason_for(classification, title, failed=failed)

    if classification["impact_type"] == "authorization_check":
        verb = "was denied authorization for" if classification["change_type"] == "denied" else "authorization checked"
        summary = f"{subject} {verb} {method or 'an operation'} on {resource}"
    elif classification["impact_type"] == "authentication":
        outcome = "failed authentication" if _is_failure(payload, event) else "authenticated"
        summary = f"{subject} {outcome} from {source_ip or source}"
    elif classification["change_type"] == "read/listed":
        summary = f"{subject} failed to read {resource}" if failed else f"{subject} read/listed {resource}"
    elif classification["change_type"] in {"created", "deleted", "updated", "configured"}:
        summary = f"{subject} {classification['change_type']} {resource}"
    else:
        summary = _as_text(getattr(event, "summary", "")) or f"{subject} performed {method or 'an audit event'} on {resource}"

    return {
        **classification,
        "event_title": title,
        "event_summary": summary,
        "decision_reason": decision_reason,
        "subject": subject,
        "subject_type": subject_type,
        "resource_display_short": resource,
        "source_context": source,
        "source_ip": source_ip,
    }


def event_digest_from_model(event: Any) -> dict[str, str]:
    return event_digest(_payload_from_event(event), event)


def decision_snapshot(payload: dict[str, Any], event: Any | None = None) -> dict[str, str]:
    digest = event_digest(payload, event)
    signal_input = {**payload, **digest}
    from src.product.event_signals import classify_signal

    signal = classify_signal(signal_input)
    return {**digest, **signal}


def decision_snapshot_from_model(event: Any) -> dict[str, str]:
    return decision_snapshot(_payload_from_event(event), event)


def flow_group_key(event: Any, window_seconds: int = 60) -> tuple[str, str, str, str, int]:
    digest = event_digest_from_model(event)
    timestamp = getattr(event, "timestamp", None)
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        bucket = int(timestamp.timestamp() // max(window_seconds, 1))
    else:
        bucket = 0
    return (
        digest["subject"],
        digest["impact_type"],
        digest["resource_family"],
        digest["resource_display_short"],
        bucket,
    )
