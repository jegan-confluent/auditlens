import logging
from typing import Any

from cachetools import LRUCache
from src.product.event_intelligence import event_digest, event_digest_from_model
from src.product.event_normalization import BULK_NOISE_METHODS


logger = logging.getLogger(__name__)

# Track unique unclassified method names so the catch-all warning fires once
# per method. Bounded at 2048 entries via LRUCache to prevent unbounded growth
# when many distinct unknown methods arrive over a long-running process lifetime.
_unknown_methods_seen: LRUCache = LRUCache(maxsize=2048)


ACTION_REQUIRED_REASONS = {
    "failure_detected",
    "denied_access",
    "destructive_change",
    "security_sensitive_change",
    "privilege_escalation",
}

# Admin-tier roles whose binding triggers a privilege-escalation alert.
# Anything outside this set (MetricsViewer, EnvironmentReader, etc.) falls
# through to the normal classification cascade.
_PRIVILEGED_ROLES: frozenset[str] = frozenset({
    "OrganizationAdmin",
    "EnvironmentAdmin",
    "CloudClusterAdmin",
})


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _field(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _digest(source: Any) -> dict[str, str]:
    if isinstance(source, dict):
        if "impact_type" in source:
            return {
                "impact_type": _as_text(source.get("impact_type")),
                "risk_level": _as_text(source.get("risk_level")),
                "change_type": _as_text(source.get("change_type")),
                "resource_family": _as_text(source.get("resource_family")),
                "event_title": _as_text(source.get("event_title")),
                "event_summary": _as_text(source.get("event_summary")),
                "subject": _as_text(source.get("subject")),
                "subject_type": _as_text(source.get("subject_type")),
                "resource_display_short": _as_text(source.get("resource_display_short")),
                "source_context": _as_text(source.get("source_context")),
                "source_ip": _as_text(source.get("source_ip")),
            }
        return event_digest(source)
    return event_digest_from_model(source)


# Derived from BULK_NOISE_METHODS minus authentication methods. Authentication
# failures (kafka.authentication, schema-registry.authentication, ksql.authenticate)
# are security signals (failed auth attempt) so they must fall through to the
# normal failure/denial cascade instead of being classified as noise.
# RBAC "Authorize" variants are excluded from this exception because a denied
# authorization check is routine expected system behavior.
_ALWAYS_NOISE_METHODS: frozenset[str] = BULK_NOISE_METHODS - frozenset({
    "kafka.authentication",
    "schema-registry.authentication",
    "ksql.authenticate",
})

# Read-only methods that don't fit the Get*/List* prefix rule below but are
# still pure reads (Tableflow's table-listing helpers) or low-signal Flink
# runtime heartbeats/metrics that emit continuously while a job runs.
_ALWAYS_INFORMATIONAL_METHODS = frozenset({
    "tableflowgettable",
    "tableflowlisttables",
    "tableflowcatalogconfig",
    "listtableflowcatalog",
    "tableflowgetcatalog",
    "tableflowlistcatalogs",
    # Flink runtime data plane: periodic, low-signal events that aren't
    # CRUD on the statement itself.
    "flinkjobrunning",
    "flinkmetrics",
    "flinkheartbeat",
})


# Flink statement / job runtime events that signal an execution-time
# failure (not a control-plane CRUD failure on the statement object).
# Routed to action_required with a domain-specific signal_reason so the
# UI can render "Flink job execution failure detected" rather than the
# generic "failure_detected" surfaced for read/destructive failures.
_FLINK_FAILURE_METHODS = frozenset({
    "flinkjobfailed",
    "flinkstatementfailed",
    "flinkjobexception",
    "checkpointfailed",
    "flinkrestartfailed",
})

# Flink lifecycle transitions — notable but not failure. Surfaced as
# attention so operators see them in the decision feed without alert
# pressure on every job start/finish.
_FLINK_LIFECYCLE_METHODS = frozenset({
    "flinkjobstarted",
    "flinkjobfinished",
    "flinkjobrestarting",
    "checkpointcompleted",
    "savepointcreated",
    "savepointrestored",
})

# FlinkJobCancelled splits on result: result=Failure routes to
# _FLINK_FAILURE_METHODS-style action_required; result=Success routes to
# lifecycle attention. Kept in a separate set so the cascade can branch.
_FLINK_CANCELLED_METHODS = frozenset({
    "flinkjobcancelled",
})


# Real-Time Context Engine (RTCE) — Confluent early-access feature.
# Substring markers checked against methodName AND serviceName so events
# without a stable method-name convention still route correctly. Match
# is case-insensitive (caller lowercases before lookup).
_RTCE_MARKERS: tuple[str, ...] = ("contextengine", "realtimecontext", "rtce")

# Bounded per-method warning seen-set for RTCE encounters. Mirrors
# `_unknown_methods_seen` but kept separate so RTCE telemetry surfaces
# even for methods that have an RTCE-specific rule (we want to learn
# the surface as Confluent ships the feature). Eviction at 512 prevents
# unbounded growth from a misconfigured method-name explosion.
_rtce_methods_seen: LRUCache = LRUCache(maxsize=512)


def _is_rtce_event(event_or_fields: Any, method_name_lower: str) -> bool:
    """True when methodName or serviceName contains an RTCE marker."""
    if any(marker in method_name_lower for marker in _RTCE_MARKERS):
        return True
    service = _as_text(
        _field(event_or_fields, "serviceName")
        or _field(event_or_fields, "service_name")
    ).lower()
    return any(marker in service for marker in _RTCE_MARKERS)

# Confluent platform automation: these org-level operations stay action_required
# even when performed by Confluent's own service account.
CONFLUENT_PLATFORM_HIGH_RISK = frozenset({
    "deleteorganization",
    "suspendorganization",
})

# Substring markers that indicate a security-sensitive mutation regardless
# of the actor. When ANY of these appears in the method name, Override 1
# (platform-automation demotion) is skipped so the main cascade can
# classify the event properly. Confluent's own service account routinely
# performs role grants/revokes/bindings, and those must NOT be demoted to
# informational just because the actor is the Confluent platform.
SECURITY_MUTATION_VERBS = frozenset({
    "grant", "revoke", "unbind", "bind",
    "deleteapi", "deleteserviceaccount",
    "revokerole", "grantrole", "assignrole",
    "removerolefromresource", "unbound",
})

# Topic name prefixes that are always Confluent-platform internals.
# Events on these topics are classified as noise regardless of the method.
_INTERNAL_TOPIC_PREFIXES = (
    "error-lcc-",    # auto-created DLQ topics for Confluent Connect/Flink (lcc- = cluster ID)
    "_confluent",    # Confluent internal metrics, tier storage, audit topics
    "__consumer_",   # Kafka consumer group offset topics
    "_schemas",      # Schema Registry internal compacted topic
)

# Methods that are relevant for internal-topic noise suppression.
# Only suppress platform-internal topic activity for these high-volume methods.
_INTERNAL_TOPIC_METHODS = frozenset({
    "kafka.createtopics",
    "kafka.produce",
    "kafka.fetch",
    "kafka.deletetopics",
    "kafka.alterconfigs",
    "kafka.describeconfigs",
    "kafka.createpartitions",
})


def _is_internal_topic(event_or_fields: Any) -> bool:
    """Return True when the resource_name matches a Confluent-internal topic pattern."""
    resource = _as_text(
        _field(event_or_fields, "resource_name")
        or _field(event_or_fields, "resourceName")
        or _field(event_or_fields, "authzResourceName")
    ).lower()
    if not resource:
        return False
    return any(resource.startswith(prefix) for prefix in _INTERNAL_TOPIC_PREFIXES)


def _is_confluent_platform(event_or_fields: Any) -> bool:
    """Return True if the actor is Confluent's own platform automation."""
    principal = _as_text(_field(event_or_fields, "principal"))
    actor = _as_text(_field(event_or_fields, "actor"))
    for val in (principal, actor):
        if "externalAccount" in val and "Confluent" in val:
            return True
    return False


def _method_name_lower(event_or_fields: Any, fallback_action: str) -> str:
    raw = _as_text(
        _field(event_or_fields, "methodName")
        or _field(event_or_fields, "method_name")
        or fallback_action
    )
    return raw.lower()


def classify_signal(event_or_fields: Any) -> dict[str, str]:
    """Classify an event and apply post-classification overrides."""
    result = _classify_signal_core(event_or_fields)
    action = _as_text(_field(event_or_fields, "action")).lower()

    # Override AT — Access Transparency events (CloudEvents
    # type "io.confluent.cloud/access-transparency") are always
    # action_required security-sensitive changes. Match on the event_type
    # field directly so classification does not depend on Confluent's
    # undocumented methodName values for this category. The existing
    # action_text-based check in _classify_signal_core remains as a
    # fallback for events where the type field is absent.
    event_type = _as_text(
        _field(event_or_fields, "type")
        or _field(event_or_fields, "event_type")
    ).lower()
    if "access-transparency" in event_type:
        return {
            "signal_type": "action_required",
            "signal_reason": "security_sensitive_change",
            "recommended_action": "Investigate immediately",
            "decision_label": "Action Needed",
        }

    # Override 0 — Confluent-internal topics (error-lcc-*, _confluent*, etc.)
    # are auto-created by the platform and produce enormous volumes of routine
    # events.  Suppress them as noise before any other override so they never
    # inflate action_required counts.
    method = _as_text(
        _field(event_or_fields, "methodName")
        or _field(event_or_fields, "method_name")
        or action
    ).lower()
    if _is_internal_topic(event_or_fields) and (
        not method or method in _INTERNAL_TOPIC_METHODS
    ):
        return {
            "signal_type": "noise",
            "signal_reason": "internal_topic",
            "recommended_action": "No action needed",
            "decision_label": "Noise",
        }

    # Override 1 — Confluent platform automation is always informational
    # unless it is a truly destructive org-level operation OR contains a
    # security-mutation verb (grant/revoke/bind/unbind/deleteapi/...). The
    # mutation-verb bypass prevents the override from swallowing real
    # security changes performed by Confluent's own service account
    # (e.g. GrantRoleResourcesForPrincipal, UnbindAllRolesForPrincipal).
    if (
        _is_confluent_platform(event_or_fields)
        and action not in CONFLUENT_PLATFORM_HIGH_RISK
        and not any(verb in action for verb in SECURITY_MUTATION_VERBS)
    ):
        return {
            "signal_type": "informational",
            "signal_reason": "platform_automation",
            "recommended_action": "No action needed",
            "decision_label": "Info",
        }

    # Override 2 — Schema RegisterSchema failures are schema evolution
    # problems, not security incidents.
    result_val = _as_text(
        _field(event_or_fields, "result")
        or _field(event_or_fields, "resultStatus")
        or _field(event_or_fields, "result_display")
    ).lower()
    if (
        result["signal_type"] == "action_required"
        and action == "schema-registry.registerschema"
        and "fail" in result_val
    ):
        return {
            "signal_type": "attention",
            "signal_reason": "schema_incompatible",
            "recommended_action": "Review schema compatibility settings",
            "decision_label": "Review",
        }

    # Override 2b — successful schema registrations are config changes.
    # Without this, _classify_signal_core leaks successful RegisterSchema
    # events to the catch-all 'unknown' bucket because no other rule
    # matches the (informational impact, attention-worthy verb) shape.
    if action == "schema-registry.registerschema" and "fail" not in result_val:
        return {
            "signal_type": "attention",
            "signal_reason": "config_changed",
            "recommended_action": "Verify schema evolution is expected",
            "decision_label": "Review",
        }

    return result


def _classify_signal_core(event_or_fields: Any) -> dict[str, str]:
    digest = _digest(event_or_fields)
    impact = digest["impact_type"]
    risk = digest["risk_level"]
    change = digest["change_type"]
    family = digest["resource_family"]
    result = _as_text(_field(event_or_fields, "result") or _field(event_or_fields, "resultStatus") or _field(event_or_fields, "result_display")).lower()
    action = _as_text(_field(event_or_fields, "action")).lower()
    normalized_action = _as_text(_field(event_or_fields, "normalized_action")).lower()
    action_text = f"{action} {normalized_action}"
    method_name = _method_name_lower(event_or_fields, action)
    is_failure = bool(_field(event_or_fields, "is_failure", False)) or any(marker in result for marker in ("fail", "error", "not_found", "not found", "404"))
    is_denied = bool(_field(event_or_fields, "is_denied", False)) or "denied" in result or change == "denied"

    # ── Early-return classifiers ───────────────────────────────────────────
    # Denial check runs FIRST so denied bulk-noise / read-only methods
    # (mds.Authorize denials, ip-filter.Authorize denials, denied GetSecret
    # reads, …) surface as action_required instead of being swallowed by
    # the auth_noise / read_only_lookup short-cuts below. Read-only and
    # routine-noise methods that merely FAIL (e.g. GetStatement 404)
    # still fall through to their respective informational / noise
    # buckets because is_failure is handled later in the cascade.
    if is_denied:
        return {
            "signal_type": "action_required",
            "signal_reason": "denied_access",
            "recommended_action": "Investigate immediately",
            "decision_label": "Action Needed",
        }
    if method_name in _ALWAYS_NOISE_METHODS:
        return {
            "signal_type": "noise",
            "signal_reason": "auth_noise",
            "recommended_action": "No action needed",
            "decision_label": "Noise",
        }
    # RTCE (Real-Time Context Engine) dispatch. Runs before the generic
    # Get/List read-only short-circuit so RTCE reads get the rtce_read
    # signal_reason rather than the generic read_only_lookup — same
    # signal_type, more specific telemetry.
    if _is_rtce_event(event_or_fields, method_name):
        if method_name not in _rtce_methods_seen:
            _rtce_methods_seen[method_name] = True
            logger.warning(
                "rtce_method_encountered method=%s action=%s",
                method_name or "<missing>",
                action or "<missing>",
            )
        if any(marker in method_name for marker in ("delete", "remove", "drop", "destroy")):
            return {
                "signal_type": "action_required",
                "signal_reason": "rtce_destructive_change",
                "recommended_action": "Confirm Real-Time Context Engine deletion was approved",
                "decision_label": "Action Needed",
            }
        if method_name.startswith(("get", "list", "describe")):
            return {
                "signal_type": "informational",
                "signal_reason": "rtce_read",
                "recommended_action": "No action needed",
                "decision_label": "Info",
            }
        return {
            "signal_type": "attention",
            "signal_reason": "rtce_config_changed",
            "recommended_action": "Verify Real-Time Context Engine change",
            "decision_label": "Review",
        }
    # Flink runtime execution-time failures. Routed here (before generic
    # is_failure) so the signal_reason is the domain-specific
    # "flink_job_failure" instead of the generic "failure_detected".
    # FlinkJobCancelled requires is_failure to qualify as a failure;
    # successful cancels fall through to the lifecycle bucket below.
    if (
        method_name in _FLINK_FAILURE_METHODS
        or (method_name in _FLINK_CANCELLED_METHODS and is_failure)
    ):
        return {
            "signal_type": "action_required",
            "signal_reason": "flink_job_failure",
            "recommended_action": "Investigate Flink job execution failure",
            "decision_label": "Action Needed",
        }
    # Flink job lifecycle transitions (and successful cancels). Notable but
    # not alerting — surfaced as attention so operators see them in the
    # decision feed.
    if (
        method_name in _FLINK_LIFECYCLE_METHODS
        or method_name in _FLINK_CANCELLED_METHODS
    ):
        return {
            "signal_type": "attention",
            "signal_reason": "flink_job_lifecycle",
            "recommended_action": "Review Flink job lifecycle event",
            "decision_label": "Review",
        }
    # Generic Get/List read-only short-circuit + _ALWAYS_INFORMATIONAL_METHODS
    # (Tableflow read helpers and Flink runtime heartbeats/metrics). Runs
    # AFTER the RTCE + Flink failure/lifecycle dispatches so RTCE-specific
    # reasons win and Flink failure methods don't get demoted by a stray
    # "get"/"list" substring at the method-name start.
    if (
        method_name.startswith("get")
        or method_name.startswith("list")
        or method_name in _ALWAYS_INFORMATIONAL_METHODS
    ):
        return {
            "signal_type": "informational",
            "signal_reason": "read_only_lookup",
            "recommended_action": "No action needed",
            "decision_label": "Info",
        }
    if is_failure:
        if impact == "read_only" or change == "read/listed":
            return {
                "signal_type": "action_required",
                "signal_reason": "failure_detected",
                "recommended_action": "Review failed read request",
                "decision_label": "Action Needed",
            }
        if impact == "destructive" or change == "deleted":
            return {
                "signal_type": "action_required",
                "signal_reason": "failure_detected",
                "recommended_action": "Investigate destructive failure",
                "decision_label": "Action Needed",
            }
        return {
            "signal_type": "action_required",
            "signal_reason": "failure_detected",
            "recommended_action": "Investigate immediately",
            "decision_label": "Action Needed",
        }
    # Privilege escalation: BindRoleForPrincipal granting an admin-tier
    # role (OrganizationAdmin / EnvironmentAdmin / CloudClusterAdmin) is
    # the highest-impact RBAC mutation in Confluent Cloud — it gives the
    # target full read/write across the scope. Per the Splunk-blog alert
    # recipe, fire action_required with a dedicated signal_reason so
    # downstream destinations can route these distinctly from generic
    # destructive_change events. Runs after is_failure / is_denied so
    # failed and denied grant attempts fall through to those buckets.
    _auth_role = _as_text(_field(event_or_fields, "auth_role")).strip()
    _auth_role_target = _as_text(_field(event_or_fields, "auth_role_target")).strip()
    if (
        "bindroleforprincipal" in method_name
        and _auth_role in _PRIVILEGED_ROLES
    ):
        target_part = f" granted to {_auth_role_target}" if _auth_role_target else ""
        return {
            "signal_type": "action_required",
            "signal_reason": "privilege_escalation",
            "recommended_action": "Confirm grant approval and review actor's authority",
            "decision_label": "Action Needed",
            "decision_reason": f"High-privilege role binding detected: {_auth_role}{target_part}",
        }

    if risk == "critical" or impact == "destructive" or change == "deleted" or any(marker in action_text for marker in ("delete", "remove", "drop", "destroy", "terminate", "unbind", "revoke")):
        return {
            "signal_type": "action_required",
            "signal_reason": "destructive_change",
            "recommended_action": "Confirm this was approved",
            "decision_label": "Action Needed",
        }
    if impact == "security_sensitive" and "access-transparency" in action_text:
        return {
            "signal_type": "action_required",
            "signal_reason": "security_sensitive_change",
            "recommended_action": "Investigate immediately",
            "decision_label": "Action Needed",
        }

    if impact == "access_change" or any(marker in action_text for marker in ("grant", "revoke", "assignrole", "remove role", "rolebinding", "bind", "unbind", "createapikey", "deleteapikey")):
        return {
            "signal_type": "attention",
            "signal_reason": "access_changed",
            "recommended_action": "Verify owner and change window",
            "decision_label": "Review",
        }
    if impact == "configuration_change" or any(marker in action_text for marker in ("updateconfig", "alterconfig", "config", "patch", "set")):
        return {
            "signal_type": "attention",
            "signal_reason": "config_changed",
            "recommended_action": "Verify owner and change window",
            "decision_label": "Review",
        }
    if risk in {"high", "medium"} or change in {"created", "updated", "configured"} or (family in {"service_account", "user", "api_key", "acl", "rbac", "network", "connector", "topic", "schema_registry", "cluster", "environment"} and impact == "constructive"):
        return {
            "signal_type": "attention",
            "signal_reason": "security_sensitive_change" if family in {"service_account", "user", "api_key", "acl", "rbac", "network"} else "config_changed",
            "recommended_action": "Review if unexpected",
            "decision_label": "Review",
        }

    if impact == "authentication":
        return {
            "signal_type": "noise",
            "signal_reason": "auth_noise",
            "recommended_action": "No action needed",
            "decision_label": "Noise",
        }
    if impact == "authorization_check":
        return {
            "signal_type": "noise",
            "signal_reason": "authorization_check",
            "recommended_action": "No action needed",
            "decision_label": "Noise",
        }
    if impact == "read_only" or change == "read/listed" or any(marker in action_text for marker in ("list", "get", "describe", "search")):
        reason = "read_only_lookup"
        if "listworkspaces" in action_text:
            reason = "read_only_lookup"
        return {
            "signal_type": "informational",
            "signal_reason": reason,
            "recommended_action": "No action needed",
            "decision_label": "Info",
        }
    if impact in {"constructive", "operational"}:
        return {
            "signal_type": "informational",
            "signal_reason": "operational_event",
            "recommended_action": "Review if unexpected",
            "decision_label": "Info",
        }
    method_name = _as_text(
        _field(event_or_fields, "methodName")
        or _field(event_or_fields, "method_name")
        or action
    ) or "<missing>"
    key = method_name.lower()[:128]
    if key not in _unknown_methods_seen:
        _unknown_methods_seen[key] = True
        logger.warning(
            "unclassified_method method=%s action=%s",
            method_name,
            action or "<missing>",
        )
    return {
        "signal_type": "informational",
        "signal_reason": "unknown",
        "recommended_action": "Review if unexpected",
        "decision_label": "Info",
    }
