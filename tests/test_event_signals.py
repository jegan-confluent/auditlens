from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import sessionmaker

from backend.app.db.database import build_engine, init_db
from backend.app.services.event_service import create_event
from backend.app.services.summary_service import get_summary
from src.product.event_signals import classify_signal
from src.product.event_normalization import normalize_event


def signal(payload: dict) -> dict[str, str]:
    return classify_signal(payload)


def test_successful_authentication_is_noise():
    result = signal({"type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"})
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "auth_noise"


def test_successful_authorization_is_noise():
    result = signal({"type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": True})
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "authorization_check"


def test_denied_authorization_is_action_required():
    result = signal({"type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": False})
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "denied_access"


def test_failed_authentication_is_action_required():
    result = signal({"type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "FAILURE"})
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "failure_detected"


def test_failed_read_only_get_is_informational():
    # Read-only methods (Get*/List*) must never escalate to action_required,
    # even on failure. A 404 from a read is a missing resource, not a
    # security or destructive event. The early-return read-only rule fires
    # before the failure cascade so the classifier keeps these as noise-tier
    # informational signals.
    result = signal({"type": "io.confluent.flink.server/request", "methodName": "GetStatement", "resultStatus": "404 NOT_FOUND"})
    assert result["signal_type"] == "informational"
    assert result["signal_reason"] == "read_only_lookup"


def test_read_only_lookup_is_informational():
    for method in ("ListWorkspaces", "GetKafkaClusters", "DescribeCluster"):
        result = signal({"type": "io.confluent.cloud/request", "methodName": method, "resultStatus": "SUCCESS"})
        assert result["signal_type"] == "informational"
        assert result["signal_reason"] == "read_only_lookup"


def test_create_topic_needs_attention_and_delete_topic_requires_action():
    create_result = signal({"type": "io.confluent.kafka.server/request", "methodName": "kafka.CreateTopics", "resourceName": "topic=orders"})
    delete_result = signal({"type": "io.confluent.kafka.server/request", "methodName": "kafka.DeleteTopics", "resourceName": "topic=orders"})
    assert create_result["signal_type"] == "attention"
    assert delete_result["signal_type"] == "action_required"
    assert delete_result["signal_reason"] == "destructive_change"


def test_config_and_access_changes_need_attention():
    config_result = signal({"type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"})
    api_key_result = signal({"type": "io.confluent.cloud/request", "methodName": "CreateAPIKey", "resourceName": "api-key=abc"})
    grant_result = signal({"type": "io.confluent.cloud/request", "methodName": "GrantRole", "resourceName": "rolebinding=abc"})
    assert config_result["signal_type"] == "attention"
    assert config_result["signal_reason"] == "config_changed"
    assert api_key_result["signal_type"] == "attention"
    assert grant_result["signal_type"] == "attention"


def test_unknown_event_has_safe_informational_fallback():
    result = signal({"methodName": "SomethingUnexpected"})
    assert result["signal_type"] == "informational"
    assert result["signal_reason"] == "unknown"


def test_flink_job_failure_methods_are_action_required():
    for method in ("FlinkJobFailed", "FlinkStatementFailed", "FlinkJobException", "CheckpointFailed", "FlinkRestartFailed"):
        result = signal({"type": "io.confluent.flink.server/request", "methodName": method, "resultStatus": "SUCCESS"})
        assert result["signal_type"] == "action_required", method
        assert result["signal_reason"] == "flink_job_failure", method


def test_flink_lifecycle_methods_are_attention():
    for method in ("FlinkJobStarted", "FlinkJobFinished", "FlinkJobRestarting", "CheckpointCompleted", "SavepointCreated", "SavepointRestored"):
        result = signal({"type": "io.confluent.flink.server/request", "methodName": method, "resultStatus": "SUCCESS"})
        assert result["signal_type"] == "attention", method
        assert result["signal_reason"] == "flink_job_lifecycle", method


def test_flink_runtime_heartbeats_are_informational():
    for method in ("FlinkJobRunning", "FlinkMetrics", "FlinkHeartbeat"):
        result = signal({"type": "io.confluent.flink.server/request", "methodName": method, "resultStatus": "SUCCESS"})
        assert result["signal_type"] == "informational", method
        assert result["signal_reason"] == "read_only_lookup", method


def test_flink_job_cancelled_splits_on_result():
    succeeded = signal({"type": "io.confluent.flink.server/request", "methodName": "FlinkJobCancelled", "resultStatus": "SUCCESS"})
    assert succeeded["signal_type"] == "attention"
    assert succeeded["signal_reason"] == "flink_job_lifecycle"
    failed = signal({"type": "io.confluent.flink.server/request", "methodName": "FlinkJobCancelled", "resultStatus": "FAILURE"})
    assert failed["signal_type"] == "action_required"
    assert failed["signal_reason"] == "flink_job_failure"


def test_rtce_method_name_dispatches_by_verb():
    delete = signal({"methodName": "DeleteContextEngine", "resultStatus": "SUCCESS"})
    assert delete["signal_type"] == "action_required"
    assert delete["signal_reason"] == "rtce_destructive_change"

    read = signal({"methodName": "GetRealTimeContext", "resultStatus": "SUCCESS"})
    assert read["signal_type"] == "informational"
    assert read["signal_reason"] == "rtce_read"

    create = signal({"methodName": "CreateContextEngine", "resultStatus": "SUCCESS"})
    assert create["signal_type"] == "attention"
    assert create["signal_reason"] == "rtce_config_changed"


def test_rtce_matches_via_service_name_when_method_is_generic():
    # Method name without an RTCE marker still routes via serviceName.
    result = signal({"methodName": "UpdateConfiguration", "serviceName": "rtce", "resultStatus": "SUCCESS"})
    assert result["signal_type"] == "attention"
    assert result["signal_reason"] == "rtce_config_changed"


def test_decision_snapshot_overrides_decision_reason_for_new_signal_reasons():
    from src.product.event_intelligence import decision_snapshot

    snap = decision_snapshot({"methodName": "FlinkJobFailed", "resultStatus": "SUCCESS"})
    assert snap["signal_reason"] == "flink_job_failure"
    assert snap["decision_reason"] == "Flink job execution failure detected"

    snap = decision_snapshot({"methodName": "FlinkJobStarted", "resultStatus": "SUCCESS"})
    assert snap["signal_reason"] == "flink_job_lifecycle"
    assert snap["decision_reason"] == "Flink job lifecycle event"

    snap = decision_snapshot({"methodName": "DeleteContextEngine", "resultStatus": "SUCCESS"})
    assert snap["signal_reason"] == "rtce_destructive_change"
    assert snap["decision_reason"] == "Real-Time Context Engine resource deleted"

    snap = decision_snapshot({"methodName": "CreateContextEngine", "resultStatus": "SUCCESS"})
    assert snap["signal_reason"] == "rtce_config_changed"
    assert snap["decision_reason"] == "Real-Time Context Engine configuration change"


def _summary_for(payloads: list[dict]) -> dict:
    with TemporaryDirectory() as tmp:
        engine = build_engine(f"sqlite:///{Path(tmp) / 'auditlens.db'}")
        init_db(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with SessionLocal() as db:
            for payload in payloads:
                create_event(db, payload)
            return get_summary(db)


def test_summary_all_noise_is_all_clear():
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            {"id": "authz-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": True},
        ]
    )
    assert summary["overall_status"] == "all_clear"
    assert summary["noise_count"] == 2


def test_summary_hide_noise_excludes_routine_noise_from_decision():
    with TemporaryDirectory() as tmp:
        engine = build_engine(f"sqlite:///{Path(tmp) / 'auditlens.db'}")
        init_db(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with SessionLocal() as db:
            create_event(
                db,
                {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            )
            create_event(
                db,
                {"id": "config-1", "type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"},
            )
            summary = get_summary(db, hide_noise=True)

    assert summary["total_events"] == 1
    assert summary["noise_count"] == 0
    assert summary["attention_count"] == 1
    assert summary["overall_status"] == "review_needed"
    assert summary["top_actions"][0]["value"] == "Connector configuration updated"


def test_summary_config_changes_need_review():
    summary = _summary_for(
        [
            {"id": "config-1", "type": "io.confluent.cloud/request", "methodName": "UpdateConnectorConfig", "resourceName": "connector=orders"},
        ]
    )
    assert summary["overall_status"] == "review_needed"
    assert summary["attention_count"] == 1


def test_summary_destructive_failures_need_action():
    summary = _summary_for(
        [
            {"id": "delete-1", "type": "io.confluent.kafka.server/request", "methodName": "kafka.DeleteTopics", "resourceName": "topic=orders"},
            {"id": "deny-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "granted": False},
        ]
    )
    assert summary["overall_status"] == "action_required"
    assert summary["action_required_count"] == 2
    assert summary["destructive_count"] == 1


def test_summary_sample_metadata_when_total_exceeds_scan_limit(monkeypatch):
    monkeypatch.setattr("backend.app.services.summary_service.SUMMARY_SCAN_LIMIT", 1)
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
            {"id": "auth-2", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "resultStatus": "SUCCESS"},
        ]
    )
    assert summary["summary_scope"] == "sampled"
    assert summary["scanned_events"] == 1
    assert summary["sample_limit"] == 1
    assert "latest 1 of 2" in summary["sample_warning"]


def test_flow_groups_prioritize_action_required_before_noise():
    summary = _summary_for(
        [
            {"id": "auth-1", "type": "io.confluent.kafka.server/authentication", "methodName": "kafka.Authentication", "principal": "u-1", "resultStatus": "SUCCESS"},
            {"id": "deny-1", "type": "io.confluent.kafka.server/authorization", "methodName": "kafka.Authorize", "principal": "u-2", "granted": False},
        ]
    )
    assert summary["flow_groups"][0]["signal_type"] == "action_required"
    assert summary["flow_groups"][0]["decision_label"] == "Action Needed"


# ── Fix 1: Confluent platform actor overrides ──────────────────────────────

def test_confluent_platform_actor_is_informational():
    # Behavioral assertion change (2026-05): the prior test pinned
    # UnbindAllRolesForPrincipal → informational, which was the B1 bug
    # (Override 1 swallowing real security mutations). The override now
    # correctly demotes only NON-security-mutation methods. Substituted
    # a benign read-only platform_automation method for the assertion.
    result = signal({
        "principal": '{"externalAccount":{"subject":"Confluent"}}',
        "action": "schema-registry.GetSubjects",
        "result": "Success",
    })
    assert result["signal_type"] == "informational"
    assert result["signal_reason"] == "platform_automation"


def test_confluent_platform_security_mutation_bypasses_override():
    # FIX B1 — when the Confluent platform actor performs a security
    # mutation (grant/revoke/bind/unbind/...), Override 1 must NOT demote
    # the event. Irreversible removals (unbind/revoke) classify as
    # destructive; reversible additions (grant/bind) classify as access
    # changes.
    unbind_result = signal({
        "principal": '{"externalAccount":{"subject":"Confluent"}}',
        "action": "schema-registry.UnbindAllRolesForPrincipal",
        "result": "Success",
    })
    assert unbind_result["signal_type"] == "action_required"
    assert unbind_result["signal_reason"] == "destructive_change"

    grant_result = signal({
        "principal": '{"externalAccount":{"subject":"Confluent"}}',
        "action": "GrantRoleResourcesForPrincipal",
        "result": "Success",
    })
    assert grant_result["signal_type"] == "attention"
    assert grant_result["signal_reason"] == "access_changed"


def test_confluent_platform_high_risk_stays_action_required():
    result = signal({
        "principal": '{"externalAccount":{"subject":"Confluent"}}',
        "action": "DeleteOrganization",
        "result": "Success",
    })
    assert result["signal_type"] == "action_required"


# ── Fix 2: Schema RegisterSchema failures → attention ─────────────────────

def test_schema_register_failure_is_attention():
    result = signal({
        "action": "schema-registry.RegisterSchema",
        "result": "FAILURE",
    })
    assert result["signal_type"] == "attention"
    assert result["signal_reason"] == "schema_incompatible"


def test_schema_register_success_keeps_original_signal():
    result = signal({
        "action": "schema-registry.RegisterSchema",
        "result": "Success",
    })
    assert result["signal_reason"] != "schema_incompatible"


# ── Operator-precedence fix: line 232 parenthesisation ────────────────────
# The fix adds explicit parentheses around (family in {...} and impact ==
# "constructive") so that Python's and-before-or rule is visible in the
# source.  The tests below pin the *intended* behavior and would fail if
# the parens were placed around the entire condition (i.e. if someone
# accidentally wrote "(A or B or C) and impact == 'constructive'", which
# would break tests 2 and 3 by returning "informational" instead of
# "attention").

def _signal_with_digest(impact_type: str, risk_level: str, change_type: str, resource_family: str, **extra) -> dict[str, str]:
    """Call classify_signal with a pre-computed digest dict to bypass event_intelligence."""
    payload = {
        "impact_type": impact_type,
        "risk_level": risk_level,
        "change_type": change_type,
        "resource_family": resource_family,
        **extra,
    }
    return signal(payload)


def test_high_risk_non_constructive_returns_attention():
    """risk="high" with any impact must return "attention".

    Would FAIL with the wrong parenthesisation (A or B or C) and impact=="constructive"
    because impact="access_change" != "constructive" would prevent the match.
    Note: access_change/destructive are caught before line 232; use an
    impact that reaches line 232 — e.g. "security_sensitive" without
    is_denied/is_failure flags.
    """
    result = _signal_with_digest(
        impact_type="security_sensitive",
        risk_level="high",
        change_type="updated",
        resource_family="cluster",
    )
    assert result["signal_type"] == "attention", (
        f"expected 'attention' for risk=high, got {result['signal_type']!r}"
    )


def test_medium_risk_constructive_returns_attention():
    """risk="medium" + impact="constructive" must return "attention".

    This is the baseline case — all interpretations agree on this.
    """
    result = _signal_with_digest(
        impact_type="constructive",
        risk_level="medium",
        change_type="created",
        resource_family="topic",
    )
    assert result["signal_type"] == "attention", (
        f"expected 'attention' for risk=medium+constructive, got {result['signal_type']!r}"
    )


def test_medium_risk_non_constructive_returns_attention():
    """risk="medium" + impact != "constructive" must still return "attention".

    Would FAIL with (A or B or C) and impact == "constructive" because
    impact="configuration_change" != "constructive" while risk="medium"
    alone SHOULD be enough to reach the attention branch.
    Note: configuration_change is caught at line 225 first, so we use
    impact="security_sensitive" with risk="medium" to reach line 232.
    """
    result = _signal_with_digest(
        impact_type="security_sensitive",
        risk_level="medium",
        change_type="updated",
        resource_family="service_account",
    )
    assert result["signal_type"] == "attention", (
        f"expected 'attention' for risk=medium+security_sensitive, got {result['signal_type']!r}"
    )


def test_low_risk_matching_family_constructive_returns_attention():
    """risk="low" + family in the checked set + impact="constructive" → "attention".

    The (family in {...} and impact == "constructive") clause fires here.
    Would still pass with or without the paren fix; included to document
    the family+constructive path.
    """
    result = _signal_with_digest(
        impact_type="constructive",
        risk_level="low",
        change_type="created",
        resource_family="service_account",
    )
    assert result["signal_type"] == "attention", (
        f"expected 'attention' for family=service_account+constructive, got {result['signal_type']!r}"
    )


def test_validate_only_create_topics_is_noise():
    """kafka.CreateTopics with validateOnly:true should classify as noise (dry-run preflight)."""
    payload = {
        "methodName": "kafka.CreateTopics",
        "validateOnly": True,
        "principal": "User:u-abc123",
        "resultStatus": "SUCCESS",
    }
    result = normalize_event(payload)
    assert result["signal_type"] == "noise"
    assert result["signal_reason"] == "dry_run_preflight"
    assert result["is_routine_noise"] is True


def test_validate_only_false_create_topics_not_suppressed():
    """kafka.CreateTopics with validateOnly:false should NOT be suppressed."""
    payload = {
        "methodName": "kafka.CreateTopics",
        "validateOnly": False,
        "principal": "User:u-abc123",
        "resultStatus": "SUCCESS",
    }
    result = normalize_event(payload)
    assert result["signal_type"] != "noise" or result["signal_reason"] != "dry_run_preflight"


# ─────────────────────────────────────────────────────────────────────────
# Feature 2: privilege-escalation alert for admin-tier BindRoleForPrincipal
# ─────────────────────────────────────────────────────────────────────────


def test_bind_role_organization_admin_is_privilege_escalation():
    """Granting OrganizationAdmin via BindRoleForPrincipal must fire
    action_required + privilege_escalation, with the role and target
    surfaced in decision_reason."""
    result = signal({
        "type": "io.confluent.cloud/request",
        "methodName": "BindRoleForPrincipal",
        "auth_role": "OrganizationAdmin",
        "auth_role_target": "User:u-new-admin",
        "resultStatus": "SUCCESS",
    })
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "privilege_escalation"
    assert "OrganizationAdmin" in result["decision_reason"]
    assert "u-new-admin" in result["decision_reason"]


def test_bind_role_cloud_cluster_admin_is_privilege_escalation():
    """CloudClusterAdmin grants are equally privileged at cluster scope."""
    result = signal({
        "type": "io.confluent.cloud/request",
        "methodName": "BindRoleForPrincipal",
        "auth_role": "CloudClusterAdmin",
        "auth_role_target": "User:u-cluster-admin",
        "resultStatus": "SUCCESS",
    })
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "privilege_escalation"


def test_bind_role_environment_admin_is_privilege_escalation():
    result = signal({
        "type": "io.confluent.cloud/request",
        "methodName": "BindRoleForPrincipal",
        "auth_role": "EnvironmentAdmin",
        "auth_role_target": "User:u-env-admin",
        "resultStatus": "SUCCESS",
    })
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "privilege_escalation"


def test_bind_role_metrics_viewer_is_not_privilege_escalation():
    """MetricsViewer (and any non-admin role) must fall through to the
    normal classification cascade — i.e., access_changed at most."""
    result = signal({
        "type": "io.confluent.cloud/request",
        "methodName": "BindRoleForPrincipal",
        "auth_role": "MetricsViewer",
        "auth_role_target": "User:u-reader",
        "resultStatus": "SUCCESS",
    })
    assert result["signal_reason"] != "privilege_escalation"
    # Should land in the access-change bucket, not action_required.
    assert result["signal_type"] in {"attention", "informational"}


def test_bind_role_denied_does_not_fire_privilege_escalation():
    """A denied OrganizationAdmin grant attempt is denied_access, not
    privilege_escalation — somebody tried but the system refused."""
    result = signal({
        "type": "io.confluent.cloud/request",
        "methodName": "BindRoleForPrincipal",
        "auth_role": "OrganizationAdmin",
        "auth_role_target": "User:u-attacker",
        "granted": False,
    })
    assert result["signal_type"] == "action_required"
    assert result["signal_reason"] == "denied_access"


def test_bind_role_extraction_from_request_data():
    """End-to-end normalization: a raw CloudEvent with role_name in
    request.data populates the auth_role + auth_role_target columns and
    routes to privilege_escalation."""
    event = {
        "id": "evt-bind-1",
        "specversion": "1.0",
        "source": "crn://confluent.cloud/organization=org1",
        "type": "io.confluent.cloud/request",
        "time": "2026-06-09T10:00:00.000Z",
        "data": {
            "methodName": "BindRoleForPrincipal",
            "authenticationInfo": {"principal": "User:admin@example.com"},
            "request": {
                "data": {
                    "role_name": "OrganizationAdmin",
                    "principal": "User:u-target",
                }
            },
            "result": {"status": "SUCCESS"},
        },
    }
    normalized = normalize_event(event)
    assert normalized["auth_role"] == "OrganizationAdmin"
    assert normalized["auth_role_target"] == "User:u-target"
    assert normalized["signal_type"] == "action_required"
    assert normalized["signal_reason"] == "privilege_escalation"
