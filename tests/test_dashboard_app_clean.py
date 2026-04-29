"""Tests for the simplified dashboard entry point."""

from pathlib import Path
import sys

import pandas as pd


DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import app_clean


def test_app_clean_imports_and_defines_only_core_tabs():
    assert app_clean.PRIMARY_TABS == ["Overview", "Audit Trail", "Failures", "Deletions", "Advanced", "Help"]


def test_clean_audit_table_maps_core_columns():
    df = pd.DataFrame(
        [
            {
                "time": "2026-04-27T10:00:00Z",
                "result_display": "SUCCESS",
                "user_display": "sa-audit",
                "action": "CreateTopic",
                "methodName": "kafka.CreateTopic",
                "resourceName": "crn://confluent.cloud/organization=o/env=e/cloud-cluster=lkc-123/topic=orders",
                "cluster_id": "lkc-123",
                "clientIp": "10.0.0.1",
            }
        ]
    )

    table = app_clean.build_clean_audit_table(df)

    assert list(table.columns) == [
        "Time",
        "Result",
        "Summary",
        "Actor",
        "Action",
        "Resource",
        "Cluster",
        "Source IP",
    ]
    assert table.iloc[0]["Time"] == "Apr 27, 2026 10:00 UTC"
    assert table.iloc[0]["Result"] == "✅ Success"
    assert table.iloc[0]["Summary"] == "sa-audit created topic 'orders'"
    assert table.iloc[0]["Actor"] == "sa-audit"
    assert table.iloc[0]["Action"] == "Create topic"
    assert table.iloc[0]["Resource"] == "Topic: orders"
    assert table.iloc[0]["Cluster"] == "lkc-123"
    assert table.iloc[0]["Source IP"] == "10.0.0.1"
    assert "crn://" not in table.iloc[0]["Resource"]


def test_core_filters_do_not_depend_on_quick_filters_or_presets():
    df = pd.DataFrame(
        [
            {
                "principal": "User:sa-123",
                "user_display": "sa-123",
                "methodName": "kafka.DeleteTopic",
                "resourceName": "orders",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "principal": "User:sa-999",
                "user_display": "sa-999",
                "methodName": "kafka.CreateTopic",
                "resourceName": "payments",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        actor_query="sa-123",
        resource_query="orders",
        action_query="Delete",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["principal"] == "User:sa-123"


def test_derive_action_category_groups_raw_methods():
    assert app_clean.derive_action_category("kafka.CreateTopics", "") == "Create"
    assert app_clean.derive_action_category("CreateTopics", "") == "Create"
    assert app_clean.derive_action_category("createTopic", "") == "Create"
    assert app_clean.derive_action_category("create topics", "") == "Create"
    assert app_clean.derive_action_category("kafka.DeleteTopics", "") == "Delete"
    assert app_clean.derive_action_category("DeleteTopics", "") == "Delete"
    assert app_clean.derive_action_category("deleteTopic", "") == "Delete"
    assert app_clean.derive_action_category("kafka.Produce", "") == "Data"
    assert app_clean.derive_action_category("kafka.Fetch", "") == "Data"
    assert app_clean.derive_action_category("Consume", "") == "Data"
    assert app_clean.derive_action_category("Read", "") == "Data"
    assert app_clean.derive_action_category("TableflowGetTable", "") == "Data"
    assert app_clean.derive_action_category("TableflowGetTable", "") != "Create"
    assert app_clean.derive_action_category("kafka.Authorize", "") == "Security"
    assert app_clean.derive_action_category("Authenticate", "") == "Security"
    assert app_clean.derive_action_category("io.confluent.kafka.server/authentication", "") == "Security"
    assert app_clean.derive_action_category("ACL", "") == "Security"
    assert app_clean.derive_action_category("RoleBinding", "") == "Security"
    assert app_clean.derive_action_category("RBAC", "") == "Security"
    assert app_clean.derive_action_category("iam.CreateApiKey", "") == "API Key"
    assert app_clean.derive_action_category("API Key", "") == "API Key"
    assert app_clean.derive_action_category("kafka.AlterConfigs", "") == "Modify"
    assert app_clean.derive_action_category("UpdateTopic", "") == "Modify"
    assert app_clean.derive_action_category("UpdateConfig", "") == "Modify"
    assert app_clean.derive_action_category("UpdateConnector", "") == "Modify"
    assert app_clean.derive_action_category("kafka.DescribeCluster", "") == "Other"


def test_action_category_filter_keeps_only_selected_intent():
    df = pd.DataFrame(
        [
            {
                "methodName": "kafka.CreateTopics",
                "action": "",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "methodName": "kafka.DeleteTopics",
                "action": "",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=payments",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "methodName": "kafka.Produce",
                "action": "",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=True,
        action_category_filter="Create",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["methodName"] == "kafka.CreateTopics"
    assert filtered.iloc[0]["action_category"] == "Create"


def test_topic_create_is_not_removed_by_routine_noise_filter():
    df = pd.DataFrame(
        [
            {
                "principal": "User:sa-pvqqxy",
                "user_display": "sa-pvqqxy",
                "methodName": "kafka.CreateTopics",
                "action": "Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=error-lcc-p76qzm",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
                "is_failure": False,
                "is_creation": True,
            }
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        action_category_filter="Create",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["user_display"] == "sa-pvqqxy"
    assert app_clean.human_summary(filtered.iloc[0]) == "sa-pvqqxy created topic 'error-lcc-p76qzm'"


def test_topic_resource_and_create_category_returns_matching_create_rows():
    df = pd.DataFrame(
        [
            {
                "principal": "User:u-75rw9o",
                "user_display": "u-75rw9o",
                "methodName": "kafka.CreateTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=jegan-testing",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "principal": "User:u-75rw9o",
                "user_display": "u-75rw9o",
                "methodName": "kafka.DeleteTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=jegan-testing",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        resource_query="jegan-testing",
        action_category_filter="Create",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["methodName"] == "kafka.CreateTopics"
    assert app_clean.human_summary(filtered.iloc[0]) == "u-75rw9o created topic 'jegan-testing'"


def test_topic_resource_text_matches_summary_only_topic_names():
    df = pd.DataFrame(
        [
            {
                "principal": "User:u-75rw9o",
                "user_display": "u-75rw9o",
                "methodName": "kafka.CreateTopics",
                "summary": "u-75rw9o created topic 'jegan-testing'",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            }
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        resource_query="jegan-testing",
        action_category_filter="Create",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["resource_name"] == "jegan-testing"


def test_topic_resource_text_matches_crn_case_insensitively():
    df = pd.DataFrame(
        [
            {
                "principal": "User:u-75rw9o",
                "user_display": "u-75rw9o",
                "methodName": "kafka.CreateTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=JEGAN-TESTING",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            }
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        resource_query="  jegan-testing  ",
        action_category_filter="Create",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["resource_name"] == "JEGAN-TESTING"


def test_routine_auth_is_hidden_but_denied_authorize_is_preserved():
    df = pd.DataFrame(
        [
            {
                "user_display": "sa-routine",
                "methodName": "Authenticate",
                "resourceName": "crn://x/cloud-cluster=lkc-1",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-denied",
                "methodName": "kafka.Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-1",
                "resultStatus": "DENIED",
                "granted": False,
                "is_failure": True,
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["user_display"] == "sa-denied"
    assert filtered.iloc[0]["action_category"] == "Security"


def test_failed_and_denied_authorize_are_not_hidden_by_routine_filter():
    df = pd.DataFrame(
        [
            {
                "user_display": "sa-failed",
                "methodName": "kafka.Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-1",
                "resultStatus": "ERROR",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-denied",
                "methodName": "kafka.Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-2",
                "resultStatus": "DENIED",
                "granted": False,
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
    )

    assert list(filtered["user_display"]) == ["sa-failed", "sa-denied"]
    assert filtered["is_denied"].tolist() == [False, True]


def test_create_topic_is_not_hidden_even_with_auth_like_action():
    df = pd.DataFrame(
        [
            {
                "user_display": "sa-create",
                "methodName": "kafka.CreateTopics",
                "action": "Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=jegan-testing",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            }
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["action_category"] == "Create"
    assert bool(filtered.iloc[0]["is_routine_noise"]) is False


def live_like_clean_dashboard_fixture():
    return pd.DataFrame(
        [
            {
                "user_display": "sa-pvqqxy",
                "methodName": "kafka.CreateTopics",
                "summary": "sa-pvqqxy created topic 'error-lcc-p76qzm'",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=error-lcc-p76qzm",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "u-75rw9o",
                "methodName": "kafka.CreateTopics",
                "summary": "u-75rw9o created topic 'jegan-testing'",
                "resourceName": "",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-pvqqxy",
                "methodName": "kafka.CreateTopics",
                "summary": "sa-pvqqxy failed to create topic 'error-lcc-p76qzm'",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=error-lcc-p76qzm",
                "resultStatus": "ERROR",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-routine",
                "methodName": "Authenticate",
                "resourceName": "crn://x/cloud-cluster=lkc-1",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-denied",
                "methodName": "kafka.Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-1",
                "resultStatus": "DENIED",
                "granted": False,
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
            {
                "user_display": "sa-tableflow",
                "methodName": "TableflowGetTable",
                "resourceName": "crn://x/cloud-cluster=lkc-1/table=orders",
                "resultStatus": "SUCCESS",
                "is_internal": False,
                "is_successful_authz_noise": False,
            },
        ]
    )


def test_live_like_topic_create_filter_path_returns_jegan_testing_and_counters():
    filtered, counters = app_clean.filter_core_events(
        live_like_clean_dashboard_fixture(),
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        resource_query="jegan-testing",
        action_category_filter="Create",
        return_counters=True,
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["user_display"] == "u-75rw9o"
    assert filtered.iloc[0]["resource_name"] == "jegan-testing"
    assert app_clean.human_summary(filtered.iloc[0]) == "u-75rw9o created topic 'jegan-testing'"
    assert counters["loaded_rows"] == 6
    assert counters["after_enrichment"] == 6
    assert counters["after_resource_type"] == 3
    assert counters["after_resource_text"] == 1
    assert counters["after_action_category"] == 1
    assert counters["after_action_text"] == 1
    assert counters["after_actor"] == 1
    assert counters["after_routine_hiding"] == 1


def test_filter_counters_show_resource_text_drop_point():
    _, counters = app_clean.filter_core_events(
        live_like_clean_dashboard_fixture(),
        hide_internal=True,
        hide_authz_noise=True,
        show_routine_auth=False,
        resource_type_filter="Topic",
        resource_query="missing-topic",
        action_category_filter="Create",
        return_counters=True,
    )

    assert counters["after_resource_type"] == 3
    assert counters["after_resource_text"] == 0
    assert counters["after_action_category"] == 0
    assert counters["after_routine_hiding"] == 0


def test_format_event_time():
    assert app_clean.format_event_time("2026-04-27T16:29:42.123Z") == "Apr 27, 2026 16:29 UTC"
    assert app_clean.format_event_time(None) == "-"
    assert app_clean.format_event_time("") == "-"
    assert app_clean.format_event_time("not-a-date") == "-"


def test_summarize_resource_known_crn_segments():
    assert app_clean.summarize_resource("crn://x/cloud-cluster=lkc-123/topic=orders") == "Topic: orders"
    assert app_clean.summarize_resource("crn://x/cloud-cluster=lkc-123") == "Cluster: lkc-123"
    assert app_clean.summarize_resource("crn://x/schema-registry=lsrc-123") == "Schema Registry: lsrc-123"
    assert app_clean.summarize_resource("crn://x/ksql=lksql-123") == "KSQL: lksql-123"
    assert app_clean.summarize_resource("crn://x/compute-pool=lfcp-123") == "Compute Pool: lfcp-123"
    assert app_clean.summarize_resource("crn://x/organization=org-123/environment=env-123") == "Environment: env-123"
    assert app_clean.summarize_resource("orders") == "orders"
    assert "crn://" not in app_clean.summarize_resource("crn://x/cloud-cluster=lkc-123/topic=orders")
    assert "crn://" not in app_clean.summarize_resource("crn://x/organization=org-123/environment=env-123")


def test_derive_resource_info_known_crn_types():
    topic = app_clean.derive_resource_info(pd.Series({
        "resourceName": "crn://x/cloud-cluster=lkc-123/topic=orders",
        "methodName": "kafka.CreateTopics",
    }))
    assert topic == {
        "resource_type": "Topic",
        "resource_name": "orders",
        "resource_display": "Topic: orders",
        "raw_resource": "crn://x/cloud-cluster=lkc-123/topic=orders",
    }

    cluster = app_clean.derive_resource_info(pd.Series({
        "resourceName": "crn://x/cloud-cluster=lkc-123",
    }))
    assert cluster["resource_type"] == "Cluster"
    assert cluster["resource_name"] == "lkc-123"
    assert cluster["resource_display"] == "Cluster: lkc-123"

    schema = app_clean.derive_resource_info(pd.Series({
        "resourceName": "crn://x/schema-registry=lsrc-123",
    }))
    assert schema["resource_type"] == "Schema Registry"
    assert schema["resource_name"] == "lsrc-123"
    assert schema["resource_display"] == "Schema Registry: lsrc-123"


def test_derive_resource_info_additional_resource_types():
    assert app_clean.derive_resource_info(pd.Series({"resourceName": "crn://x/ksql=lksql-123"}))["resource_type"] == "KSQL"
    assert app_clean.derive_resource_info(pd.Series({"resourceName": "crn://x/compute-pool=lfcp-123"}))["resource_type"] == "Compute Pool"
    assert app_clean.derive_resource_info(pd.Series({"methodName": "GetConnectors", "resourceName": "connector-orders"}))["resource_type"] == "Connector"
    assert app_clean.derive_resource_info(pd.Series({"methodName": "CreateApiKey", "resourceName": "api key abc"}))["resource_type"] == "API Key"
    assert app_clean.derive_resource_info(pd.Series({"methodName": "kafka.CreateAcls", "resourceName": "acl binding"}))["resource_type"] == "ACL / RBAC"


def test_humanize_action_core_cases():
    rows = [
        ({"methodName": "kafka.CreateTopics"}, "Create topic"),
        ({"methodName": "kafka.DeleteTopics"}, "Delete topic"),
        ({"methodName": "io.confluent.kafka.server/authentication"}, "Kafka authentication"),
        ({"methodName": "io.confluent.sg.server/authentication"}, "Schema Registry authentication"),
        ({"action": "Authentication", "resourceName": "crn://x/schema-registry=lsrc-123"}, "Schema Registry authentication"),
        ({"action": "Authenticate", "resourceName": "crn://x/cloud-cluster=lkc-123"}, "Kafka authentication"),
        ({"methodName": "kafka.Authorize", "resourceType": "COMPUTE_POOL"}, "Authorize compute pool"),
        ({"methodName": "kafka.CreateAcls"}, "Create ACL"),
        ({"methodName": "kafka.DeleteAcl"}, "Delete ACL"),
        ({"methodName": "GetKafkaClusters"}, "Fetch cluster metadata"),
        ({"methodName": "ListComputePools"}, "List compute pools"),
        ({"methodName": "GetStatement"}, "Fetch statement"),
    ]

    for payload, expected in rows:
        assert app_clean.humanize_action(pd.Series(payload)) == expected


def test_routine_auth_noise_filter_hides_only_low_signal_successes():
    df = pd.DataFrame(
        [
            {
                "methodName": "other.path",
                "action": "Authentication",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "cluster",
            },
            {
                "methodName": "kafka.Authorize",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "topic",
            },
            {
                "methodName": "kafka.Authorize",
                "resultStatus": "DENIED",
                "is_failure": True,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "topic",
            },
            {
                "methodName": "kafka.CreateTopics",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": False,
                "is_creation": True,
                "resourceName": "orders",
            },
            {
                "methodName": "kafka.CreateAcls",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": False,
                "is_creation": True,
                "resourceName": "acl",
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=False,
    )

    assert list(filtered["methodName"]) == ["kafka.Authorize", "kafka.CreateTopics", "kafka.CreateAcls"]
    assert len(app_clean.filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=True,
    )) == 5


def test_routine_metadata_events_hidden_by_default():
    df = pd.DataFrame(
        [
            {"methodName": "GetKafkaClusters", "resultStatus": "SUCCESS", "is_failure": False, "is_deletion": False, "is_creation": False},
            {"methodName": "ListComputePools", "resultStatus": "-", "is_failure": False, "is_deletion": False, "is_creation": False},
            {"methodName": "GetConnectors", "resultStatus": "SUCCESS", "is_failure": False, "is_deletion": False, "is_creation": False},
            {"methodName": "kafka.CreateTopics", "resultStatus": "SUCCESS", "is_failure": False, "is_deletion": False, "is_creation": True},
            {"methodName": "GetKafkaClusters", "resultStatus": "DENIED", "is_failure": True, "is_deletion": False, "is_creation": False},
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=False,
    )

    assert list(filtered["methodName"]) == ["kafka.CreateTopics", "GetKafkaClusters"]


def test_resource_type_filter_keeps_only_topics():
    df = pd.DataFrame(
        [
            {"methodName": "kafka.CreateTopics", "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders", "resultStatus": "SUCCESS", "is_failure": False, "is_deletion": False, "is_creation": True},
            {"methodName": "GetKafkaClusters", "resourceName": "crn://x/cloud-cluster=lkc-1", "resultStatus": "DENIED", "is_failure": True, "is_deletion": False, "is_creation": False},
            {"methodName": "GetConnectors", "resourceName": "connector-payments", "resultStatus": "ERROR", "is_failure": True, "is_deletion": False, "is_creation": False},
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=False,
        resource_type_filter="Topic",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["resourceName"].endswith("/topic=orders")


def test_failure_and_denied_events_are_preserved_when_noise_filtering():
    df = pd.DataFrame(
        [
            {
                "methodName": "kafka.Authorize",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "crn://x/cloud-cluster=lkc-noise",
            },
            {
                "methodName": "kafka.Authorize",
                "resultStatus": "DENIED",
                "is_failure": True,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "crn://x/cloud-cluster=lkc-denied",
            },
            {
                "methodName": "GetConnectors",
                "resultStatus": "ERROR",
                "is_failure": True,
                "is_deletion": False,
                "is_creation": False,
                "resourceName": "crn://x/cloud-cluster=lkc-failure",
            },
            {
                "methodName": "kafka.DeleteTopics",
                "resultStatus": "SUCCESS",
                "is_failure": False,
                "is_deletion": True,
                "is_creation": False,
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
            },
        ]
    )

    filtered = app_clean.filter_core_events(
        df,
        hide_internal=False,
        hide_authz_noise=False,
        show_routine_auth=False,
    )

    assert list(filtered["methodName"]) == ["kafka.Authorize", "GetConnectors", "kafka.DeleteTopics"]
    assert "lkc-noise" not in "\n".join(filtered["resourceName"].astype(str).tolist())


def test_get_kafka_clusters_is_not_classified_as_acl_or_rbac_event():
    row = pd.Series({
        "methodName": "GetKafkaClusters",
        "resourceName": "crn://x/environment=env-abc",
    })

    assert app_clean.is_acl_rbac_event(row) is False


def test_row_detail_sections_expose_normalized_and_raw_fields():
    row = pd.Series({
        "time": "2026-04-27T10:00:00Z",
        "user_display": "sa-audit",
        "user_email": "audit@example.com",
        "principal": "User:sa-audit",
        "methodName": "kafka.DeleteTopics",
        "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
        "authzResourceName": "Topic:orders",
        "resultStatus": "DENIED",
        "granted": False,
        "is_failure": True,
        "cluster_id": "lkc-1",
        "environment_id": "env-1",
        "clientIp": "10.0.0.1",
        "clientId": "client-1",
        "requestId": "req-123",
        "raw": {"methodName": "kafka.DeleteTopics"},
    })

    normalized, raw = app_clean.row_detail_sections(row)

    assert normalized == {
        "Time": "Apr 27, 2026 10:00 UTC",
        "Actor": "sa-audit",
        "Actor email/name": "audit@example.com",
        "Action": "Delete topic",
        "Result": "⚠️ Denied",
        "Resource Type": "Topic",
        "Resource Name": "orders",
        "Resource Display": "Topic: orders",
        "Cluster": "lkc-1",
        "Environment": "env-1",
        "Source IP": "10.0.0.1",
        "Client ID": "client-1",
    }
    assert raw["methodName"] == "kafka.DeleteTopics"
    assert raw["resourceName"] == "crn://x/cloud-cluster=lkc-1/topic=orders"
    assert raw["authzResourceName"] == "Topic:orders"
    assert raw["principal"] == "User:sa-audit"
    assert raw["resultStatus"] == "DENIED"
    assert raw["granted"] == "False"
    assert raw["request/client ID"] == "req-123"
    assert raw["full raw JSON"] == {"methodName": "kafka.DeleteTopics"}
    assert raw["resourceName"] != normalized["Resource Display"]


def test_normalized_result_replaces_dash_and_null_values():
    assert app_clean.normalized_result(pd.Series({"resultStatus": "-"})) == "Neutral"
    assert app_clean.normalized_result(pd.Series({"result_display": "—"})) == "Neutral"
    assert app_clean.normalized_result(pd.Series({"resultStatus": None, "result_display": None})) == "Unknown"
    assert app_clean.normalized_result(pd.Series({"resultStatus": ""})) == "Unknown"
    assert app_clean.normalized_result(pd.Series({"resultStatus": "SUCCESS"})) == "✅ Success"
    assert app_clean.normalized_result(pd.Series({"resultStatus": "DENIED", "is_failure": True})) == "⚠️ Denied"


def test_html_table_contains_expected_columns_and_no_crn():
    table = pd.DataFrame([{
        "Time": "Apr 27, 2026 10:00 UTC",
        "Result": "Neutral",
        "Summary": "sa-xyz created topic 'orders'",
        "Actor": "sa-xyz",
        "Action": "Create topic",
        "Resource": "Topic: orders",
        "Cluster": "lkc-123",
        "Source IP": "10.0.0.1",
    }])

    html = app_clean.render_audit_html_table(table)

    for column in ["Time", "Result", "Summary", "Actor", "Action", "Resource", "Cluster", "Source IP"]:
        assert f">{column}<" in html
    assert "sa-xyz created topic &#x27;orders&#x27;" in html
    assert "crn://" not in html
    assert "lkc-123" in html
    assert "10.0.0.1" in html


def test_html_table_layout_uses_fixed_widths_and_nowrap_for_compact_fields():
    source = Path(app_clean.__file__).read_text()

    assert "layout=\"wide\"" in source
    assert ".audit-table .col-time { width: 130px;" in source
    assert ".audit-table .col-result { width: 100px;" in source
    assert ".audit-table .col-summary { width: 360px;" in source
    assert ".audit-table .col-actor { width: 190px;" in source
    assert ".audit-table .col-action { width: 140px;" in source
    assert ".audit-table .col-resource { width: 220px;" in source
    assert ".audit-table .col-cluster { width: 110px;" in source
    assert ".audit-table .col-ip { width: 120px;" in source
    assert ".audit-table-wrap" in source and "overflow-x: auto;" in source
    assert ".audit-table .col-cluster { width: 110px; color: #667085; font-size: 0.8rem; white-space: nowrap;" in source
    assert ".audit-table .col-ip { width: 120px; color: #667085; font-size: 0.8rem; white-space: nowrap;" in source


def test_sidebar_keeps_required_compact_filters_and_no_run_caption():
    source = Path(app_clean.__file__).read_text()

    for label in [
        '"Time Window"',
        '"Max Events"',
        '"Show routine auth/authz events"',
        '"Actor"',
        '"Resource Type"',
        '"Resource"',
        '"Action Category"',
        '"Action"',
        '"Refresh Data"',
    ]:
        assert label in source

    assert "Groups operations by intent (Create, Delete, Data access, Security, etc.)" in source
    assert '"Actor or service account"' not in source
    assert '"Resource name"' not in source
    assert '"Action or method"' not in source
    assert "Run clean dashboard:" not in source
    assert "[data-testid=\"stSidebar\"]" in source


def test_audit_trail_does_not_render_onboarding_panels_above_table():
    source = Path(app_clean.__file__).read_text()
    audit_trail_body = source.split("def _render_audit_trail", 1)[1].split("def _render_failures", 1)[0]

    assert "Use the Summary column first" not in audit_trail_body
    assert "render_context_hint" not in audit_trail_body
    assert "Recent audit events with the core fields needed for investigation." not in audit_trail_body
    assert "To find who created or deleted a topic" in audit_trail_body
    assert "_render_clean_table" in audit_trail_body


def test_overview_only_renders_guided_demo_and_signal_banners():
    source = Path(app_clean.__file__).read_text()
    main_body = source.split("def main()", 1)[1]
    navigation_index = main_body.index("selected_tab = st.radio")
    overview_index = main_body.index('if selected_tab == "Overview":')
    audit_trail_index = main_body.index('elif selected_tab == "Audit Trail":')

    assert main_body.index("render_first_time_onboarding_banner()") > overview_index
    assert main_body.index("render_focus_strip(df, storage)") > overview_index
    assert main_body.index("render_failure_cta(df)") > overview_index
    assert main_body.index("render_first_time_onboarding_banner()") > navigation_index

    audit_trail_branch = main_body[audit_trail_index:main_body.index('elif selected_tab == "Failures":')]
    assert "render_first_time_onboarding_banner" not in audit_trail_branch
    assert "render_focus_strip" not in audit_trail_branch
    assert "render_failure_cta" not in audit_trail_branch


def test_human_summary_formats_readable_sentences():
    assert app_clean.human_summary(pd.Series({
        "user_display": "sa-xyz",
        "methodName": "kafka.CreateTopics",
        "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
        "resultStatus": "SUCCESS",
    })) == "sa-xyz created topic 'orders'"

    assert app_clean.human_summary(pd.Series({
        "user_display": "sa-abc",
        "methodName": "kafka.DeleteTopics",
        "resourceName": "crn://x/cloud-cluster=lkc-1/topic=payments",
        "is_failure": True,
        "resultStatus": "ERROR",
    })) == "sa-abc failed to delete topic 'payments'"

    assert app_clean.human_summary(pd.Series({
        "user_display": "u-123 (user@example.com)",
        "action": "Authentication",
        "resourceName": "crn://x/schema-registry=lsrc-123",
        "resultStatus": "-",
    })) == "u-123 authenticated with Schema Registry"


def test_human_summary_metadata_and_denied_authorize_cases():
    assert app_clean.human_summary(pd.Series({
        "user_display": "sa-xyz",
        "methodName": "GetKafkaClusters",
        "resourceName": "crn://x/environment=env-abc",
        "resultStatus": "SUCCESS",
    })) == "sa-xyz fetched cluster metadata for env-abc"

    assert app_clean.human_summary(pd.Series({
        "user_display": "sa-xyz",
        "methodName": "ListComputePools",
        "resourceName": "crn://x/environment=env-abc",
        "resultStatus": "SUCCESS",
    })) == "sa-xyz listed compute pools in env-abc"

    assert app_clean.human_summary(pd.Series({
        "user_display": "sa-xyz",
        "methodName": "kafka.Authorize",
        "resourceName": "crn://x/cloud-cluster=lkc-123",
        "resultStatus": "DENIED",
        "is_failure": True,
    })) == "sa-xyz was denied access to cluster 'lkc-123'"

    assert app_clean.human_summary(pd.Series({
        "user_display": "u-123",
        "methodName": "GetStatement",
        "resourceName": "c360-loyalty-revenue-job",
        "resultStatus": "ERROR",
        "is_failure": True,
    })) == "u-123 failed to fetch statement 'c360-loyalty-revenue-job'"


def test_closeout_summary_examples_regression():
    examples = [
        (
            {
                "user_display": "sa-xyz",
                "methodName": "GetKafkaClusters",
                "resourceName": "crn://x/environment=env-abc",
                "resultStatus": "SUCCESS",
            },
            "sa-xyz fetched cluster metadata for env-abc",
        ),
        (
            {
                "user_display": "sa-xyz",
                "methodName": "ListComputePools",
                "resourceName": "crn://x/environment=env-abc",
                "resultStatus": "SUCCESS",
            },
            "sa-xyz listed compute pools in env-abc",
        ),
        (
            {
                "user_display": "sa-xyz",
                "methodName": "kafka.CreateTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
                "resultStatus": "SUCCESS",
            },
            "sa-xyz created topic 'orders'",
        ),
        (
            {
                "user_display": "sa-xyz",
                "methodName": "kafka.DeleteTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
                "resultStatus": "SUCCESS",
            },
            "sa-xyz deleted topic 'orders'",
        ),
        (
            {
                "user_display": "sa-xyz",
                "methodName": "kafka.CreateTopics",
                "resourceName": "crn://x/cloud-cluster=lkc-1/topic=orders",
                "resultStatus": "ERROR",
                "is_failure": True,
            },
            "sa-xyz failed to create topic 'orders'",
        ),
        (
            {
                "user_display": "sa-xyz",
                "methodName": "kafka.Authorize",
                "resourceName": "crn://x/cloud-cluster=lkc-123",
                "resultStatus": "DENIED",
                "is_failure": True,
            },
            "sa-xyz was denied access to cluster 'lkc-123'",
        ),
        (
            {
                "user_display": "sa-xyz",
                "action": "Authentication",
                "resourceName": "crn://x/schema-registry=lsrc-123",
                "resultStatus": "SUCCESS",
            },
            "sa-xyz authenticated with Schema Registry",
        ),
    ]

    for payload, expected in examples:
        assert app_clean.human_summary(pd.Series(payload)) == expected


def test_signal_severity_color_logic():
    assert app_clean.signal_class("failures", 1) == "signal-red"
    assert app_clean.signal_class("failures", 0) == "signal-green"
    assert app_clean.signal_class("deletions", 1) == "signal-orange"
    assert app_clean.signal_class("deletions", 0) == "signal-green"
    assert app_clean.signal_class("storage", 26) == "signal-green"
    assert app_clean.signal_class("storage", 60) == "signal-yellow"
    assert app_clean.signal_class("storage", 80) == "signal-amber"
    assert app_clean.signal_class("storage", 90) == "signal-red"
    assert app_clean.storage_card_severity(59) == "ok"
    assert app_clean.storage_card_severity(60) == "warn"
    assert app_clean.storage_card_severity(80) == "orange"
    assert app_clean.storage_card_severity(90) == "bad"


def test_focus_strip_renders_signal_badges(monkeypatch):
    rendered = []
    monkeypatch.setattr(app_clean.st, "markdown", lambda value, **_kwargs: rendered.append(value))
    df = pd.DataFrame(
        [
            {"time": "2026-04-27T10:00:00Z", "is_failure": True, "is_deletion": False},
            {"time": "2026-04-27T10:01:00Z", "is_failure": False, "is_deletion": True},
        ]
    )

    app_clean.render_focus_strip(df, {"current_db_size": 20, "max_db_size": 100})

    html = rendered[0]
    assert "focus-strip" in html
    assert "Failures: 2" not in html
    assert "Failures: 1" in html
    assert "Deletions: 1" in html
    assert "Storage 20%" in html


def test_failure_cta_appears_only_when_failures_exist(monkeypatch):
    rendered = []
    monkeypatch.setattr(app_clean.st, "markdown", lambda value, **_kwargs: rendered.append(value))

    app_clean.render_failure_cta(pd.DataFrame([{"time": "2026-04-27T10:00:00Z", "is_failure": False}]))
    assert rendered == []

    app_clean.render_failure_cta(pd.DataFrame([{"time": "2026-04-27T10:00:00Z", "is_failure": True}]))
    assert "Investigate failures in the Failures tab." in rendered[0]


def test_extract_storage_summary_reads_nested_forwarder_health_contract():
    summary = app_clean.extract_storage_summary(
        {
            "status": "healthy",
            "observability": {
                "persistence_storage": {
                    "current_db_size": 1356670912,
                    "max_db_size": 5368709120,
                    "storage_mode": "normal",
                    "hot_cache_retention_hours": 24,
                    "last_rotation_time": "2026-04-27T16:00:00Z",
                    "archive_enabled": False,
                }
            },
        }
    )

    assert summary == {
        "status": "healthy",
        "current_db_size": 1356670912,
        "max_db_size": 5368709120,
        "storage_mode": "normal",
        "hot_cache_retention_hours": 24,
        "last_rotation_time": "2026-04-27T16:00:00Z",
        "archive_enabled": False,
    }


def test_app_clean_source_does_not_render_old_filter_surfaces():
    source = Path(app_clean.__file__).read_text()

    assert "render_quick_filters" not in source
    assert "apply_quick_filter" not in source
    assert "filter_presets" not in source
    assert "preset_selector" not in source


def test_onboarding_markdown_loads_and_injects_guided_demo_anchor():
    markdown = app_clean.load_onboarding_markdown()

    assert markdown is not None
    assert "AuditLens Clean Onboarding Walkthrough" in markdown
    assert "Guided Demo Flow" in markdown

    anchored = app_clean.help_markdown_with_anchor(markdown)
    assert f'id="{app_clean.HELP_GUIDED_DEMO_ANCHOR}"' in anchored
    assert app_clean.help_markdown_with_anchor(anchored).count(app_clean.HELP_GUIDED_DEMO_ANCHOR) == 1


def test_onboarding_markdown_missing_file_returns_none(tmp_path):
    assert app_clean.load_onboarding_markdown(tmp_path / "missing.md") is None


def test_demo_flow_step_helpers_stay_in_bounds():
    assert app_clean.previous_demo_step(0) == 0
    assert app_clean.previous_demo_step(3) == 2
    assert app_clean.next_demo_step(0, total_steps=3) == 1
    assert app_clean.next_demo_step(2, total_steps=3) == 2
    assert app_clean.next_demo_step(0, total_steps=0) == 0


def test_set_active_tab_updates_session_state(monkeypatch):
    session = {}
    monkeypatch.setattr(app_clean.st, "session_state", session)

    app_clean.set_active_tab("Help", anchor=app_clean.HELP_GUIDED_DEMO_ANCHOR)
    assert session["active_tab"] == "Help"
    assert session["help_anchor"] == app_clean.HELP_GUIDED_DEMO_ANCHOR

    app_clean.set_active_tab("Not A Tab")
    assert session["active_tab"] == "Overview"
