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


# Methods we treat as pure noise: produce/fetch traffic, authentication,
# and authorization-check fanout. None of these need actor enrichment,
# event intelligence, or resource criticality scoring — they're routine
# data plane and access-check chatter.
BULK_NOISE_METHODS: frozenset[str] = frozenset({
    'mds.authorize',
    'kafka.fetch',
    'kafka.produce',
    'flink.authenticate',
    'flink.authorize',
    'schema-registry.authentication',
    'schema-registry.authorize',
    'kafka.authentication',
    'scheduledjwksrefresh',
    'ksql.authenticate',
    'ksql.authorize',
    'ip-filter.authorize',
})


def is_bulk_noise(method_name: str | None) -> bool:
    """True when the event is high-volume noise that the bulk lane should
    handle with the minimal-normalize fast path."""
    if not method_name:
        return False
    return str(method_name).lower() in BULK_NOISE_METHODS


# Columns physically stored in audit_events_noise (migration 0007). The
# noise table is deliberately lean — every column is paid for on every
# INSERT — so minimal_normalize returns *exactly* these fields. Decision
# fields (signal_type, signal_reason, etc.) are constants for noise rows
# and are hardcoded by the API layer when it serves /events?show_noise=true
# and /summary/methods, so we don't waste a column storing them.
NOISE_TABLE_FIELDS: tuple[str, ...] = (
    "timestamp",
    "actor",
    "action",
    "result",
    "resource_name",
    "source_ip",
    "environment_id",
    "cluster_id",
    "is_denied",
)


def _principal_to_scalar(value: Any) -> str:
    """Reduce a CloudEvents principal object to a scalar string id.

    Mirrors audit_forwarder._to_scalar but lives here so event_normalization
    has no upstream import. Returns '' if no recognizable id can be found.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("confluentServiceAccount", "confluentUser", "identityPool", "group"):
            inner = value.get(key)
            if isinstance(inner, dict):
                rid = inner.get("resourceId")
                if rid:
                    return str(rid).strip()
        # Top-level resourceId on principal itself
        rid = value.get("resourceId")
        if rid:
            return str(rid).strip()
    return ""


def _client_ip_from_data(data: dict[str, Any]) -> str:
    """Best-effort client IP extraction from CloudEvents data block.

    Checks the three known nesting paths (matches audit_forwarder._extract_client_ip)
    without raising on shape surprises.
    """
    if not isinstance(data, dict):
        return ""
    candidates = (
        data.get("clientAddress"),
        (data.get("requestMetadata") or {}).get("clientAddress")
        if isinstance(data.get("requestMetadata"), dict) else None,
        (data.get("authorizationInfo") or {}).get("requestMetadata", {}).get("clientAddress")
        if isinstance(data.get("authorizationInfo"), dict)
        and isinstance(data["authorizationInfo"].get("requestMetadata"), dict)
        else None,
    )
    for addr in candidates:
        if isinstance(addr, list) and addr:
            first = addr[0]
            if isinstance(first, dict):
                ip = first.get("ip") or first.get("address")
                if ip:
                    return str(ip).strip()
        elif isinstance(addr, dict):
            ip = addr.get("ip") or addr.get("address")
            if ip:
                return str(ip).strip()
    return ""


def _extract_crn_segment(text: Any, marker: str) -> str:
    """Pull the value after `marker=` from a CRN-shaped string. Returns ''
    if the input is not a CRN or the marker is absent."""
    if not isinstance(text, str) or not text:
        return ""
    pattern = rf"{re.escape(marker)}=([^/]+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def minimal_normalize(event: dict[str, Any]) -> dict[str, Any]:
    """Fast path for bulk-noise events.

    Returns *exactly* the columns physically stored in audit_events_noise:
    timestamp, actor, action, result, resource_name, source_ip,
    environment_id, cluster_id, is_denied. Skips IAM enrichment, decision
    snapshot, resource intelligence, and signal cascade. Target: < 1ms
    per event.

    Robust to two input shapes:
      - Raw CloudEvents from Kafka (data.methodName, data.authenticationInfo, …)
      - Flat dicts produced by flatten_audit (methodName at top level)

    Never raises — every extraction step uses .get with a safe default and
    is wrapped against shape surprises. On a fully malformed input, returns
    sentinel values (action='', actor='unknown', etc.) so the row can still
    be inserted.
    """
    if not isinstance(event, dict):
        event = {}
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    auth_info = data.get("authenticationInfo") if isinstance(data.get("authenticationInfo"), dict) else {}
    authz_info = data.get("authorizationInfo") if isinstance(data.get("authorizationInfo"), dict) else {}

    # action / methodName: nested first (raw CloudEvents), then flat fallback.
    action = (
        data.get("methodName")
        or event.get("methodName")
        or event.get("method")
        or event.get("action")
        or ""
    )

    # actor: principal extraction handles both dict-shaped principals (raw)
    # and pre-scalarized strings (flat dicts post flatten_audit).
    principal_raw = auth_info.get("principal")
    actor = _principal_to_scalar(principal_raw) or str(
        event.get("principal")
        or event.get("principal_raw")
        or event.get("actor")
        or event.get("user_display")
        or event.get("user")
        or "unknown"
    ).strip()
    if not actor:
        actor = "unknown"

    # is_denied: authorizationInfo.granted is the canonical signal; fall
    # back to top-level granted (set by flatten_audit) and the explicit
    # is_denied flag. None means "no opinion" → not denied.
    granted = authz_info.get("granted")
    if granted is None:
        granted = event.get("granted")
    is_denied = bool(event.get("is_denied")) or granted is False

    # result: 'Success' / 'Failure'. Failure when denied OR when
    # data.result.status / top-level resultStatus carries a fail/error
    # marker. Match the conservative substring check used elsewhere.
    result_status = ""
    raw_result = data.get("result") if isinstance(data.get("result"), dict) else None
    if raw_result is not None:
        result_status = str(raw_result.get("status") or "")
    if not result_status:
        result_status = str(event.get("resultStatus") or event.get("result") or "")
    result_lower = result_status.lower()
    is_failure_flag = (
        bool(event.get("is_failure"))
        or is_denied
        or any(marker in result_lower for marker in ("fail", "error", "denied", "not_found", "404"))
    )
    result = "Failure" if is_failure_flag else "Success"

    # resource_name: nested first, fall back to flattened top-level fields.
    resource_name = (
        data.get("resourceName")
        or authz_info.get("resourceName")
        or event.get("resourceName")
        or event.get("resource_name")
        or event.get("authzResourceName")
        or ""
    )

    # source IP: top-level (post flatten_audit's _extract_client_ip) wins;
    # otherwise dig into data.{requestMetadata,authorizationInfo}.clientAddress.
    source_ip = (
        event.get("clientIp")
        or event.get("source_ip")
        or _client_ip_from_data(data)
    )

    # environment_id / cluster_id: prefer pre-extracted top-level values
    # (set by flatten_audit), otherwise re-parse the CRN sources we have.
    environment_id = (
        event.get("environment_id")
        or event.get("environmentId")
        or _extract_crn_segment(event.get("source"), "environment")
        or _extract_crn_segment(event.get("subject"), "environment")
        or _extract_crn_segment(data.get("resourceName"), "environment")
        or ""
    )
    cluster_id = (
        event.get("cluster_id")
        or event.get("clusterId")
    )
    if not cluster_id:
        for crn_source in (event.get("source"), event.get("subject"), data.get("resourceName")):
            for marker in ("kafka", "schema-registry", "ksqldb", "flink"):
                cluster_id = _extract_crn_segment(crn_source, marker)
                if cluster_id:
                    break
            if cluster_id:
                break
    cluster_id = cluster_id or ""

    timestamp = parse_event_timestamp(event)

    return {
        "timestamp": timestamp,
        "actor": str(actor)[:255],
        "action": str(action)[:255] if action else "",
        "result": result,
        "resource_name": str(resource_name)[:512] if resource_name else None,
        "source_ip": str(source_ip)[:128] if source_ip else None,
        "environment_id": str(environment_id)[:255] if environment_id else None,
        "cluster_id": str(cluster_id)[:255] if cluster_id else None,
        "is_denied": is_denied,
    }


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

    # Reads of API keys are Data, not API Key. The API Key bucket should
    # reflect mutations only — checked before the API Key step.
    if "getapikey" in compact or "listapikey" in compact:
        return "Data"
    # SignIn is an authentication-class event; bucket as Security so it does
    # not land in the catch-all Other bucket.
    if "signin" in compact:
        return "Security"
    if "apikey" in compact or "api key" in lowered:
        return "API Key"
    # ACL / RBAC and access-control changes (revoke / grant / invite). Confluent
    # emits Revoke/GrantRoleResourcesForPrincipal and InviteUser as
    # access-control mutations that previously fell to Other.
    if (
        any(marker in compact for marker in (
            "createacl", "createacls", "deleteacl", "deleteacls",
            "rolebinding", "rbac",
            "revoke", "grant", "inviteuser", "revokerole", "grantrole",
            "bindrole",
        ))
        or re.search(r"\bacl\b", lowered)
    ):
        return "Security"
    if "createtopic" in compact or "createtopics" in compact:
        return "Create"
    if "deletetopic" in compact or "deletetopics" in compact:
        return "Delete"
    # Specific Data markers first; then word-boundary regex so the long tail
    # of Get*/List*/Describe* methods land in Data instead of Other.
    if any(marker in compact for marker in (
        "getstatement", "liststatements", "tableflowgettable",
        "tableflowlisttables", "tableflowoauthtokens",
        "listtables", "listnamespaces",
        "produce", "fetch", "consume", "read",
    )):
        return "Data"
    if (
        re.search(r"\bget[a-z]+\b", lowered)
        or re.search(r"\blist[a-z]+\b", lowered)
        or re.search(r"\bdescribe[a-z]+\b", lowered)
    ):
        return "Data"
    if any(marker in compact for marker in ("authorize", "authorization", "authentication", "authenticate")):
        return "Security"
    # Delete equivalents include the schema-registry deregister-{dek,kek,keypair}
    # methods which previously fell through.
    if "delete" in compact or any(marker in compact for marker in (
        "deregisterdek", "deregisterkek", "deregisterkeypair",
    )):
        return "Delete"
    # pause/resume/suspend/restart are operational state toggles — bucket as
    # Modify (PauseConnector, ResumeExporter, PauseKsqldbCluster, ...).
    if any(marker in compact for marker in (
        "updatestatement", "patchstatement", "alter", "update", "modify", "config",
        "pause", "resume", "suspend", "restart",
    )):
        return "Modify"
    # Schema Registry register-{schema,dek,kek,keypair} are Create equivalents.
    if "create" in compact or any(marker in compact for marker in (
        "registerschema", "registerdek", "registerkek", "registerkeypair",
    )):
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


def _is_management_plane(payload: dict[str, Any]) -> bool:
    data = _data(payload)
    method = _as_text(
        payload.get("methodName") or payload.get("method_name")
        or data.get("methodName") or ""
    ).lower()
    return not method.startswith("kafka.")


def event_fingerprint(payload: dict[str, Any]) -> str:
    # Management-plane events (non-kafka) use a content fingerprint so
    # Confluent double-emits (same operation, different message IDs) collapse
    # to a single row. The fingerprint covers actor+action+resource+second so
    # rapid-but-distinct operations are not incorrectly merged.
    if _is_management_plane(payload):
        normalized = normalize_event(payload)
        ts_second = parse_event_timestamp(payload).replace(microsecond=0).isoformat()
        stable = {
            "actor": normalized["actor"],
            "action": normalized["action"],
            "resource_name": normalized["resource_name"],
            "timestamp": ts_second,
        }
        return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()
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
