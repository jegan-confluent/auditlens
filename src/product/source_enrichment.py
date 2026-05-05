import json
from typing import Any


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value).strip()


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


def _scope_resource_id(resources: Any, resource_type: str) -> str:
    if not isinstance(resources, list):
        return ""
    wanted = resource_type.upper()
    for item in resources:
        if not isinstance(item, dict):
            continue
        item_type = _as_text(item.get("resourceType") or item.get("type")).upper()
        if item_type == wanted:
            return _as_text(item.get("resourceId") or item.get("id"))
    return ""


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _client_address_ip(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return _as_text(first.get("ip") or first.get("address"))
        return _as_text(first)
    if isinstance(value, dict):
        return _as_text(value.get("ip") or value.get("address"))
    return _as_text(value)


def extract_source_info(payload: dict[str, Any], event: Any | None = None) -> dict[str, str | None]:
    data = _data(payload)
    cloud_resources = _cloud_resources(payload)
    scope_resources = _nested(cloud_resources, "scope", "resources")
    request_metadata = _nested(data, "requestMetadata") or payload.get("requestMetadata") or {}
    environment_id = (
        _as_text(payload.get("environment_id") or payload.get("environmentId"))
        or _scope_resource_id(scope_resources, "ENVIRONMENT")
        or _as_text(getattr(event, "environment_id", ""))
    )
    flink_region = (
        _as_text(payload.get("flink_region") or payload.get("flinkRegion"))
        or _scope_resource_id(scope_resources, "FLINK_REGION")
        or _as_text(getattr(event, "flink_region", ""))
    )
    network_id = _as_text(payload.get("network_id") or payload.get("networkId") or _scope_resource_id(scope_resources, "NETWORK") or getattr(event, "network_id", ""))
    cluster_id = _as_text(payload.get("cluster_id") or payload.get("clusterId") or _scope_resource_id(scope_resources, "KAFKA_CLUSTER") or getattr(event, "cluster_id", ""))
    source_ip = (
        _as_text(payload.get("clientIp"))
        or _as_text(payload.get("source_ip"))
        or _as_text(payload.get("sourceIp"))
        or _as_text(payload.get("sourceAddress"))
        or _client_address_ip(_nested(data, "requestMetadata", "clientAddress"))
        or _client_address_ip(_nested(request_metadata, "clientAddress"))
        or _client_address_ip(payload.get("clientAddress"))
        or _as_text(getattr(event, "source_ip", ""))
    )
    client_id = _as_text(payload.get("clientId") or _nested(data, "request", "clientId") or _nested(request_metadata, "clientId"))
    connection_id = _as_text(payload.get("connectionId") or _nested(data, "request", "connectionId") or _nested(request_metadata, "connectionId"))
    request_id = _as_text(payload.get("requestId") or payload.get("id") or _nested(data, "request", "requestId") or _nested(request_metadata, "requestId"))
    service_name = _as_text(payload.get("serviceName") or payload.get("service_name") or data.get("serviceName"))
    proxy_context = _as_text(payload.get("proxyContext") or data.get("proxyContext") or _nested(request_metadata, "proxyContext"))
    source_context = environment_id or cluster_id or network_id or None

    if source_ip:
        source_display = source_ip
        source_reason = "client_ip"
    elif service_name or proxy_context:
        source_display = "Internal/control-plane"
        source_reason = "internal_control_plane"
    else:
        source_display = "Not provided by audit event"
        source_reason = "missing"

    return {
        "source_ip": source_ip or None,
        "source_display": source_display,
        "source_reason": source_reason,
        "client_id": client_id or None,
        "connection_id": connection_id or None,
        "request_id": request_id or None,
        "source_context": source_context,
        "environment_id": environment_id or None,
        "flink_region": flink_region or None,
        "network_id": network_id or None,
    }
