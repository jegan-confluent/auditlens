from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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
    "service account": "service_account",
    "service_account": "service_account",
    "serviceaccount": "service_account",
    "compute pool": "compute_pool",
    "compute_pool": "compute_pool",
    "flink": "compute_pool",
    "ksql": "ksqldb",
    "ksqldb": "ksqldb",
    "ksql db": "ksqldb",
    "statement": "statement",
    "flink_statement": "statement",
    "tableflow": "tableflow",
    "organization": "organization",
    "network": "network",
    "user": "user",
    "unknown": "unknown",
    # Confluent emits these compact / camelCase variants that previously fell
    # through to the raw lowercased string. Map them to canonical types so
    # the dashboard stops splitting the same logical concept across multiple
    # chips.
    "cloudapikey": "api_key",
    "flinkenvironmentregionapikey": "api_key",
    "serviceaccountapikey": "api_key",
    "clusterapikey": "api_key",
    "identitypool": "identity_pool",
    "identityprovider": "identity_provider",
    "customconnectorplugin": "custom_connector_plugin",
    "byokkey": "byok_key",
    "securitysso": "sso_connection",
    "multifactorauthentication": "mfa",
    "notificationintegration": "notification",
    "notificationsubscription": "notification",
    "healthpluscluster": "cluster",
    "usmkafkacluster": "cluster",
    "usmconnectcluster": "cluster",
    # camelCase variant emitted by some Confluent control-plane events
    "kafkacluster": "cluster",
    "computepool": "compute_pool",
    "flink_workspace": "workspace",
    "privatelinkattachment": "private_link",
    "privatelinkattachmentconnection": "private_link",
    "privatelinkaccess": "private_link",
    "transitgatewayattachment": "transit_gateway",
    "peering": "peering",
    "aichatcompletions": "ai",
    "billing": "billing",
    "audit": "audit",
    "supportplan": "organization",
    "streamlineage": "lineage",
    "connectartifact": "connector",
    "flinkartifact": "compute_pool",
    "dnsrecord": "network",
    "identity_provider": "identity_provider",
    "identity_pool": "identity_pool",
    "role_binding": "role_binding",
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
    "service_account": "Service Account",
    "compute_pool": "Compute Pool",
    "ksqldb": "KSQLDB",
    "statement": "Statement",
    "tableflow": "Tableflow",
    "organization": "Organization",
    "network": "Network",
    "user": "User",
    "unknown": "Unknown",
}

SENSITIVE_RESOURCE_TYPES = {"organization", "environment", "cluster", "api_key", "service_account", "user", "role_binding", "network"}
SCOPED_RESOURCE_TYPES = {"topic", "connector", "subject", "schema_registry", "statement", "compute_pool", "ksqldb", "tableflow"}


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


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def canonical_resource_type(value: Any) -> str:
    text = _as_text(value).replace("-", "_").strip().lower()
    text = re.sub(r"[_\s]+", " ", text)
    return RESOURCE_TYPE_ALIASES.get(text, RESOURCE_TYPE_ALIASES.get(text.replace(" ", "_"), text.replace(" ", "_") or "unknown"))


def resource_type_label(value: Any) -> str:
    canonical = canonical_resource_type(value)
    return RESOURCE_TYPE_LABELS.get(canonical, canonical.replace("_", " ").title())


@dataclass(frozen=True)
class CRNComponents:
    raw: str
    is_valid: bool = False
    organization_id: str | None = None
    environment_id: str | None = None
    cluster_type: str | None = None
    cluster_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    all_components: dict[str, str] | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "crn_raw": self.raw,
            "crn_organization_id": self.organization_id,
            "crn_environment_id": self.environment_id,
            "crn_cluster_type": self.cluster_type,
            "crn_cluster_id": self.cluster_id,
            "crn_resource_type": self.resource_type,
            "crn_resource_id": self.resource_id,
        }


@dataclass(frozen=True)
class ResourceContext:
    resource_id: str
    resource_type: str
    resource_name: str
    resource_display_name: str
    cluster_id: str | None
    cluster_name: str | None
    environment_id: str | None
    environment_name: str | None
    parent_resource: str | None
    resource_scope: str
    resource_criticality: str
    blast_radius_hint: str
    production_hint: str
    resource_source: str
    resource_confidence: str
    raw_resource: str
    raw_crn: str | None
    flink_region: str | None
    metadata: dict[str, Any]

    def to_event_fields(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "resource_display": self.resource_display_name,
            "resource_display_name": self.resource_display_name,
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "environment_id": self.environment_id,
            "environment_name": self.environment_name,
            "parent_resource": self.parent_resource,
            "resource_scope": self.resource_scope,
            "resource_criticality": self.resource_criticality,
            "blast_radius_hint": self.blast_radius_hint,
            "production_hint": self.production_hint,
        }

    def to_catalog_record(self, *, seen_at: datetime | None = None) -> dict[str, Any]:
        seen = seen_at or datetime.now(timezone.utc)
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "display_name": self.resource_display_name,
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "environment_id": self.environment_id,
            "environment_name": self.environment_name,
            "parent_resource": self.parent_resource,
            "resource_scope": self.resource_scope,
            "resource_criticality": self.resource_criticality,
            "blast_radius_hint": self.blast_radius_hint,
            "production_hint": self.production_hint,
            "source": self.resource_source,
            "metadata_json": json.dumps(self.metadata, sort_keys=True, default=str),
            "first_seen_at": seen,
            "last_seen_at": seen,
        }


def parse_crn(crn: str | None) -> CRNComponents:
    if not crn:
        return CRNComponents(raw="", is_valid=False, all_components={})
    if not crn.startswith("crn://confluent.cloud/"):
        return CRNComponents(raw=crn, is_valid=False, all_components={})
    path = crn[len("crn://confluent.cloud/") :]
    if not path:
        return CRNComponents(raw=crn, is_valid=True, all_components={})
    components: dict[str, str] = {}
    for segment in path.split("/"):
        if "=" in segment:
            key, value = segment.split("=", 1)
            components[key] = value
    result = CRNComponents(
        raw=crn,
        is_valid=True,
        all_components=components,
        organization_id=components.get("organization"),
        environment_id=components.get("environment"),
    )
    for cluster_type in ("kafka", "schema-registry", "ksqldb", "flink", "connect", "cloud-cluster"):
        if cluster_type in components:
            result = CRNComponents(
                raw=crn,
                is_valid=True,
                all_components=components,
                organization_id=result.organization_id,
                environment_id=result.environment_id,
                cluster_type=cluster_type if cluster_type != "cloud-cluster" else None,
                cluster_id=components[cluster_type],
            )
            break
    for resource_type in (
        "topic",
        "group",
        "transactional-id",
        "cluster-link",
        "subject",
        "connector",
        "statement",
        "compute-pool",
        "service-account",
        "user",
        "api-key",
        "identity-pool",
        "identity-provider",
        "network",
        "peering",
        "private-link",
    ):
        if resource_type in components:
            result = CRNComponents(
                raw=crn,
                is_valid=True,
                all_components=components,
                organization_id=result.organization_id,
                environment_id=result.environment_id,
                cluster_type=result.cluster_type,
                cluster_id=result.cluster_id,
                resource_type=resource_type,
                resource_id=components[resource_type],
            )
            break
    if result.cluster_type is None and result.cluster_id:
        if result.cluster_id.startswith("lkc-"):
            result = CRNComponents(**{**result.__dict__, "cluster_type": "kafka"})
        elif result.cluster_id.startswith("lsrc-"):
            result = CRNComponents(**{**result.__dict__, "cluster_type": "schema-registry"})
        elif result.cluster_id.startswith("lksqlc-"):
            result = CRNComponents(**{**result.__dict__, "cluster_type": "ksqldb"})
        elif result.cluster_id.startswith("lfcp-"):
            result = CRNComponents(**{**result.__dict__, "cluster_type": "flink"})
    return result


def _resource_path(payload: dict[str, Any]) -> tuple[str, ...]:
    return (
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
        "environment_id",
        "subject",
    )


def _extract_marker_value(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1]
    for separator in ("/", ":", " "):
        if separator in tail:
            tail = tail.split(separator, 1)[0]
    return tail.strip("'\" ")


def _extract_quoted_topic(text: str) -> str:
    match = re.search(r"topic\s+['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _cloud_resources(payload: dict[str, Any]) -> dict[str, Any]:
    data = _data(payload)
    value = payload.get("cloudResources") or data.get("cloudResources")
    if isinstance(value, dict):
        return value
    return _load_json(value)


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("data"), dict):
        return payload["data"]
    return _load_json(payload.get("data_json"))


def _event_text(event: Any | None, *names: str) -> str:
    if event is None:
        return ""
    for name in names:
        if name in {
            "cluster_name",
            "environment_name",
            "resource_display_name",
            "parent_resource",
            "resource_scope",
            "resource_criticality",
            "blast_radius_hint",
            "production_hint",
        }:
            value = _as_text(getattr(event, f"_{name}", "") or event.__dict__.get(name, ""))
        else:
            value = _as_text(event.__dict__.get(name, getattr(event, name, "")))
        if value:
            return value
    return ""


def _scope_resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    resources = _nested(_cloud_resources(payload), "scope", "resources")
    return resources if isinstance(resources, list) else []


def _resource_from_scope(payload: dict[str, Any], resource_type: str) -> str:
    wanted = resource_type.upper()
    for item in _scope_resources(payload):
        if not isinstance(item, dict):
            continue
        item_type = _as_text(item.get("resourceType") or item.get("type")).upper()
        if item_type == wanted:
            return _as_text(item.get("resourceId") or item.get("id") or item.get("name"))
    return ""


def _source_from_path(path: str) -> tuple[str, str]:
    if path == "cloud_resources.resource":
        return "cloud_resources.resource", "high"
    if path == "crn":
        return "crn", "high"
    if path == "payload":
        return "payload", "medium"
    if path == "scope":
        return "scope", "medium"
    if path == "heuristic":
        return "heuristic", "low"
    return "fallback", "low"


def _production_hint(*values: str) -> str:
    text = " ".join(value for value in values if value).lower()
    if any(marker in text for marker in ("prod", "production", "prd", "live")):
        return "production_likely"
    if any(marker in text for marker in ("dev", "test", "qa", "sandbox", "stage", "staging", "demo")):
        return "non_production_likely"
    return "unknown"


def _criticality(resource_type: str) -> str:
    canonical = canonical_resource_type(resource_type)
    if canonical in SENSITIVE_RESOURCE_TYPES:
        return "high"
    if canonical in SCOPED_RESOURCE_TYPES:
        return "medium"
    if canonical == "unknown":
        return "unknown"
    return "low"


def _blast_radius_hint(resource_type: str, environment_id: str | None, cluster_id: str | None) -> str:
    canonical = canonical_resource_type(resource_type)
    if canonical == "organization":
        return "organization-wide"
    if canonical == "environment":
        return "environment-wide"
    if canonical == "cluster":
        return "cluster-wide"
    if canonical in {"api_key", "service_account", "user", "role_binding"}:
        return "identity-scoped"
    if canonical in {"network"}:
        return "network-scoped"
    if environment_id and cluster_id:
        return "cluster-scoped"
    if environment_id:
        return "environment-scoped"
    if canonical in SCOPED_RESOURCE_TYPES:
        return "resource-scoped"
    return "unknown"


def _scope_path(resource_type: str, environment_id: str | None, cluster_id: str | None, flink_region: str | None) -> str:
    segments: list[str] = []
    canonical = canonical_resource_type(resource_type)
    if environment_id:
        segments.append(f"environment:{environment_id}")
    if cluster_id:
        segments.append(f"cluster:{cluster_id}")
    if flink_region:
        segments.append(f"flink_region:{flink_region}")
    if canonical not in {"environment", "cluster", "organization", "unknown"}:
        segments.append(f"{canonical}")
    return " > ".join(segments) if segments else "unknown"


def _parent_resource(resource_type: str, environment_id: str | None, cluster_id: str | None, flink_region: str | None) -> str | None:
    canonical = canonical_resource_type(resource_type)
    if canonical in {"organization"}:
        return None
    if canonical == "environment":
        return None
    if canonical == "cluster":
        return f"environment:{environment_id}" if environment_id else None
    if canonical == "statement" and flink_region:
        return f"environment:{environment_id}" if environment_id else f"flink_region:{flink_region}"
    if cluster_id:
        return f"cluster:{cluster_id}"
    if environment_id:
        return f"environment:{environment_id}"
    return None


def _resource_id(raw_crn: str | None, resource_type: str, resource_name: str, environment_id: str | None, cluster_id: str | None, parent_resource: str | None) -> str:
    if raw_crn:
        return raw_crn
    parts = [canonical_resource_type(resource_type) or "unknown"]
    if environment_id:
        parts.append(f"environment:{environment_id}")
    if cluster_id:
        parts.append(f"cluster:{cluster_id}")
    if parent_resource:
        parts.append(f"parent:{parent_resource}")
    parts.append(f"name:{resource_name or '-'}")
    return "|".join(parts)


def _resource_display(resource_type: str, resource_name: str, raw_resource: str) -> str:
    canonical = canonical_resource_type(resource_type)
    label = resource_type_label(canonical)
    if resource_name and resource_name != "-":
        return f"{label}: {resource_name}"
    if raw_resource:
        return summarize_resource(raw_resource)
    return label


def summarize_resource(value: Any) -> str:
    text = _as_text(value).strip()
    if not text:
        return "-"
    for marker, label in (
        ("/topic=", "Topic"),
        ("/connector=", "Connector"),
        ("/schema-registry=", "Schema Registry"),
        ("/ksql=", "KSQLDB"),
        ("/compute-pool=", "Compute Pool"),
        ("/statement=", "Statement"),
        ("/cloud-cluster=", "Cluster"),
        ("/environment=", "Environment"),
        ("/service-account=", "Service Account"),
        ("/user=", "User"),
        ("/api-key=", "API Key"),
        ("/apikey=", "API Key"),
        ("/network=", "Network"),
        ("/organization=", "Organization"),
    ):
        if marker in text:
            value = _extract_marker_value(text, marker)
            return f"{label}: {value}" if value else label
    if text.lower().startswith("topic="):
        return f"Topic: {text.split('=', 1)[1].strip()}"
    return text if len(text) <= 96 else f"{text[:93]}..."


def extract_resource_context(payload: dict[str, Any], event: Any | None = None) -> ResourceContext:
    data = _data(payload)
    cloud_resources = _cloud_resources(payload)
    primary = cloud_resources.get("resource") if isinstance(cloud_resources, dict) else None
    scope_resources = _scope_resources(payload)
    raw_resource = ""
    raw_crn = ""
    resource_type = "unknown"
    resource_name = "-"
    cluster_id = _as_text(payload.get("cluster_id") or payload.get("clusterId") or _event_text(event, "cluster_id")) or None
    environment_id = _as_text(payload.get("environment_id") or payload.get("environmentId") or _event_text(event, "environment_id")) or None
    flink_region = _as_text(payload.get("flink_region") or payload.get("flinkRegion")) or _resource_from_scope(payload, "FLINK_REGION") or None
    cluster_name = _as_text(payload.get("cluster_name") or payload.get("clusterName") or _event_text(event, "cluster_name")) or None
    environment_name = _as_text(payload.get("environment_name") or payload.get("environmentName") or _event_text(event, "environment_name")) or None
    source_path = "fallback"
    confidence = "low"

    if isinstance(primary, dict):
        resource_type = canonical_resource_type(primary.get("resourceType") or primary.get("type"))
        resource_name = _as_text(primary.get("resourceId") or primary.get("id") or primary.get("name")) or "-"
        raw_resource = resource_name
        source_path = "cloud_resources.resource"
        confidence = "high"
        if resource_type == "cluster":
            cluster_id = cluster_id or resource_name
            cluster_name = _as_text(primary.get("displayName") or primary.get("display_name") or primary.get("name")) or cluster_name
        elif resource_type == "environment":
            environment_id = environment_id or resource_name
            environment_name = _as_text(primary.get("displayName") or primary.get("display_name") or primary.get("name")) or environment_name
        raw_crn_candidate = _as_text(primary.get("crn") or primary.get("resourceName") or primary.get("resource_name")) or ""
        raw_crn = raw_crn_candidate if raw_crn_candidate.startswith("crn://") else ""
        if not raw_crn:
            payload_crn_candidate = _as_text(payload.get("resourceName") or payload.get("authzResourceName")) or ""
            raw_crn = payload_crn_candidate if payload_crn_candidate.startswith("crn://") else ""
        if raw_crn and raw_crn.startswith("crn://"):
            parsed = parse_crn(raw_crn)
            cluster_id = cluster_id or parsed.cluster_id
            environment_id = environment_id or parsed.environment_id
            if not resource_name or resource_name == "-":
                resource_name = parsed.resource_id or resource_name
    else:
        candidate_fields = _resource_path(payload)
        search_text = " ".join(_as_text(payload.get(field)) for field in candidate_fields)
        resource_type_hint = _as_text(payload.get("resourceType") or payload.get("resource_type"))
        for field in candidate_fields:
            value = _as_text(payload.get(field))
            if not value:
                continue
            raw_resource = value
            if value.startswith("crn://"):
                parsed = parse_crn(value)
                raw_crn = value
                source_path = "crn"
                confidence = "high"
                if parsed.resource_type:
                    resource_type = canonical_resource_type(parsed.resource_type)
                if parsed.resource_id:
                    resource_name = parsed.resource_id
                cluster_id = cluster_id or parsed.cluster_id
                environment_id = environment_id or parsed.environment_id
                break
        if raw_crn == "" and raw_resource:
            marker_types = (
                ("/topic=", "topic"),
                ("/cloud-cluster=", "cluster"),
                ("/schema-registry=", "schema_registry"),
                ("/ksql=", "ksqldb"),
                ("/compute-pool=", "compute_pool"),
                ("/statement=", "statement"),
                ("/connector=", "connector"),
                ("/service-account=", "service_account"),
                ("/api-key=", "api_key"),
                ("/apikey=", "api_key"),
                ("/network=", "network"),
                ("/organization=", "organization"),
                ("/environment=", "environment"),
            )
            for marker, label in marker_types:
                if marker in raw_resource:
                    resource_type = canonical_resource_type(label)
                    extracted = _extract_marker_value(raw_resource, marker)
                    if extracted:
                        resource_name = extracted
                    source_path = "payload"
                    confidence = "medium"
                    break
        if resource_type == "unknown" and raw_crn:
            parsed = parse_crn(raw_crn)
            cluster_kind = (parsed.cluster_type or "").lower()
            if parsed.resource_type:
                resource_type = canonical_resource_type(parsed.resource_type)
                if parsed.resource_id:
                    resource_name = parsed.resource_id
            elif cluster_kind == "ksqldb":
                resource_type = "ksqldb"
                resource_name = parsed.cluster_id or cluster_id or resource_name
            elif cluster_kind == "schema-registry":
                resource_type = "schema_registry"
                resource_name = parsed.cluster_id or cluster_id or resource_name
            elif cluster_kind == "flink":
                resource_type = "compute_pool"
                resource_name = parsed.cluster_id or cluster_id or resource_name
            elif cluster_kind in {"kafka", "connect", "cloud-cluster"}:
                resource_type = "cluster"
                resource_name = parsed.cluster_id or cluster_id or resource_name
            elif cluster_id:
                resource_type = "cluster"
                resource_name = cluster_id if resource_name == "-" else resource_name
            elif environment_id:
                resource_type = "environment"
                resource_name = environment_id if resource_name == "-" else resource_name
            if resource_type != "unknown":
                source_path = "crn"
                confidence = "high"
        if resource_type == "unknown":
            if _as_text(payload.get("topic_name")):
                resource_type = "topic"
                resource_name = _as_text(payload.get("topic_name"))
                source_path = "payload"
                confidence = "medium"
            elif "topic" in search_text.lower():
                resource_type = "topic"
                quoted_topic = _extract_quoted_topic(search_text)
                if quoted_topic:
                    resource_name = quoted_topic
                source_path = "heuristic"
            elif resource_type_hint:
                resource_type = canonical_resource_type(resource_type_hint)
                source_path = "payload"
                confidence = "medium"
            elif any(marker in search_text.lower() for marker in ("subject=", "/subject=", "schema subject")):
                resource_type = "subject"
                source_path = "heuristic"
            elif "connector" in search_text.lower():
                resource_type = "connector"
                source_path = "heuristic"
            elif "apikey" in search_text.lower() or "api key" in search_text.lower():
                resource_type = "api_key"
                source_path = "heuristic"
            elif any(marker in search_text.lower() for marker in ("createacl", "deleteacl", "acl:", "/acl=", " rbac", "rolebinding", "role binding")):
                resource_type = "role_binding"
                source_path = "heuristic"
            elif "environment" in search_text.lower() or "/environment=" in search_text.lower():
                resource_type = "environment"
                source_path = "heuristic"
            elif "tableflow" in search_text.lower():
                resource_type = "tableflow"
                source_path = "heuristic"
            elif "cluster" in search_text.lower() or resource_type_hint.upper() in {"CLUSTER", "KAFKA_CLUSTER"}:
                resource_type = "cluster"
                source_path = "heuristic"

        if raw_resource == "":
            event_resource_display = _event_text(event, "resource_display")
            event_resource_name = _event_text(event, "resource_name")
            event_resource_type = _event_text(event, "resource_type")
            if event_resource_display:
                raw_resource = event_resource_display
            elif event_resource_name:
                raw_resource = event_resource_name
            if event_resource_name and resource_name == "-":
                resource_name = event_resource_name
            if resource_type == "unknown" and event_resource_type:
                resource_type = canonical_resource_type(event_resource_type)
                if resource_type != "unknown":
                    source_path = "event"
                    confidence = "medium"
            if cluster_id is None and _event_text(event, "cluster_id"):
                cluster_id = _event_text(event, "cluster_id") or None
            if environment_id is None and _event_text(event, "environment_id"):
                environment_id = _event_text(event, "environment_id") or None
            if cluster_name is None and _event_text(event, "cluster_name"):
                cluster_name = _event_text(event, "cluster_name") or None
            if environment_name is None and _event_text(event, "environment_name"):
                environment_name = _event_text(event, "environment_name") or None

        if resource_name == "-":
            quoted_topic = _extract_quoted_topic(search_text)
            if resource_type == "topic" and quoted_topic:
                resource_name = quoted_topic
            elif raw_resource:
                resource_name = summarize_resource(raw_resource)
                if ":" in resource_name:
                    resource_name = resource_name.split(":", 1)[1].strip()
            elif cluster_id:
                resource_name = cluster_id

    if cluster_id is None:
        # Confluent scopes use "KAFKA_CLUSTER" (schema) and "KAFKA" (older events).
        _scope_cluster = _resource_from_scope(payload, "KAFKA") or _resource_from_scope(payload, "KAFKA_CLUSTER")
        if _scope_cluster and _scope_cluster not in {"", "-"}:
            cluster_id = _scope_cluster
    if environment_id is None:
        scope_env = _resource_from_scope(payload, "ENVIRONMENT")
        if scope_env:
            environment_id = scope_env
    if resource_type == "statement" and not cluster_id and flink_region:
        cluster_id = None

    # CreateKafkaCluster (and similar methods) target a cluster, but the
    # resourceName CRN may only reference the parent environment (the cluster
    # doesn't yet exist at request time). If we now have the cluster_id from
    # scope or the cloudResources.resource block, promote to cluster type so
    # resource_name and event_summary reflect the cluster, not its parent env.
    if resource_type == "environment" and cluster_id:
        _m = _as_text(payload.get("methodName") or payload.get("method_name")).lower().replace("_", "").replace("-", "")
        if any(op in _m for op in ("kafkacluster", "createcluster", "deletecluster", "updatecluster", "resumecluster", "pausecluster")):
            resource_type = "cluster"
            resource_name = cluster_id

    parent_resource = _parent_resource(resource_type, environment_id, cluster_id, flink_region)
    resource_scope = _scope_path(resource_type, environment_id, cluster_id, flink_region)
    resource_display_name = _resource_display(resource_type, resource_name, raw_resource)
    resource_criticality = _criticality(resource_type)
    blast_radius_hint = _blast_radius_hint(resource_type, environment_id, cluster_id)
    production_hint = _production_hint(resource_name, cluster_id or "", environment_id or "", raw_resource, _as_text(getattr(event, "summary", "")))
    resource_id = _resource_id(raw_crn or None, resource_type, resource_name, environment_id, cluster_id, parent_resource)
    if source_path == "fallback" and resource_name not in {"", "-"}:
        source_path = "payload"
        confidence = "medium"
    metadata = {
        "raw_payload_keys": sorted(str(key) for key in payload.keys()),
        "raw_resource": raw_resource or None,
        "raw_crn": raw_crn or None,
        "scope_resources": [
            {
                "resourceType": _as_text(item.get("resourceType") or item.get("type")),
                "resourceId": _as_text(item.get("resourceId") or item.get("id") or item.get("name")),
            }
            for item in scope_resources
            if isinstance(item, dict)
        ],
    }
    return ResourceContext(
        resource_id=resource_id,
        resource_type=canonical_resource_type(resource_type),
        resource_name=resource_name or "-",
        resource_display_name=resource_display_name,
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        environment_id=environment_id,
        environment_name=environment_name,
        parent_resource=parent_resource,
        resource_scope=resource_scope,
        resource_criticality=resource_criticality,
        blast_radius_hint=blast_radius_hint,
        production_hint=production_hint,
        resource_source=source_path,
        resource_confidence=confidence if confidence in {"high", "medium", "low"} else "low",
        raw_resource=raw_resource or "-",
        raw_crn=raw_crn or None,
        flink_region=flink_region,
        metadata=metadata,
    )


def build_resource_catalog_entry(payload: dict[str, Any], event: Any | None = None, *, seen_at: datetime | None = None) -> dict[str, Any]:
    return extract_resource_context(payload, event).to_catalog_record(seen_at=seen_at)


def resource_display_short(payload: dict[str, Any], event: Any | None = None) -> str:
    context = extract_resource_context(payload, event)
    if context.resource_name and context.resource_name != "-":
        return context.resource_name
    if context.raw_resource:
        return summarize_resource(context.raw_resource)
    return "Unknown"


def resource_summary_from_context(context: ResourceContext) -> dict[str, Any]:
    return context.to_event_fields()


def resource_catalog_key(context: ResourceContext) -> str:
    return context.resource_id
