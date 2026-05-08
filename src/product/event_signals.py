import logging
from typing import Any

from src.product.event_intelligence import event_digest, event_digest_from_model


logger = logging.getLogger(__name__)

# Track unique unclassified method names so the catch-all warning fires once
# per method per process. Without this guard a single unmapped method that
# arrives at high QPS would flood the log.
_unknown_methods_seen: set[str] = set()


ACTION_REQUIRED_REASONS = {
    "failure_detected",
    "denied_access",
    "destructive_change",
    "security_sensitive_change",
}


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


def classify_signal(event_or_fields: Any) -> dict[str, str]:
    digest = _digest(event_or_fields)
    impact = digest["impact_type"]
    risk = digest["risk_level"]
    change = digest["change_type"]
    family = digest["resource_family"]
    result = _as_text(_field(event_or_fields, "result") or _field(event_or_fields, "resultStatus") or _field(event_or_fields, "result_display")).lower()
    action = _as_text(_field(event_or_fields, "action")).lower()
    normalized_action = _as_text(_field(event_or_fields, "normalized_action")).lower()
    action_text = f"{action} {normalized_action}"
    is_failure = bool(_field(event_or_fields, "is_failure", False)) or any(marker in result for marker in ("fail", "error", "not_found", "not found", "404"))
    is_denied = bool(_field(event_or_fields, "is_denied", False)) or "denied" in result or change == "denied"

    if is_denied:
        return {
            "signal_type": "action_required",
            "signal_reason": "denied_access",
            "recommended_action": "Investigate immediately",
            "decision_label": "Action Needed",
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
    if risk == "critical" or impact == "destructive" or change == "deleted" or any(marker in action_text for marker in ("delete", "remove", "drop", "destroy", "terminate")):
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

    if impact == "access_change" or any(marker in action_text for marker in ("grant", "revoke", "assignrole", "remove role", "rolebinding", "createapikey", "deleteapikey")):
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
    if risk in {"high", "medium"} or change in {"created", "updated", "configured"} or family in {"service_account", "user", "api_key", "acl", "rbac", "network", "connector", "topic", "schema_registry", "cluster", "environment"} and impact == "constructive":
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
        _unknown_methods_seen.add(key)
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
