import pytest

from src.product.resource_intelligence import canonical_resource_type, extract_resource_context, parse_crn, resource_type_label


def test_parse_malformed_crn_is_safe():
    parsed = parse_crn("invalid://confluent.cloud/organization=abc123/environment=env1")
    assert parsed.raw == "invalid://confluent.cloud/organization=abc123/environment=env1"
    assert parsed.is_valid is False
    assert parsed.organization_id is None
    assert parsed.environment_id is None


@pytest.mark.parametrize(
    "crn, expected_type, expected_name",
    [
        ("crn://confluent.cloud/organization=o-1/environment=env-1", "environment", "env-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1", "cluster", "lkc-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1/topic=orders", "topic", "orders"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/connect=lc-1/connector=orders-sink", "connector", "orders-sink"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/schema-registry=lsrc-1/subject=orders-value", "subject", "orders-value"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/service-account=sa-1", "service_account", "sa-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/api-key=ak-1", "api_key", "ak-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/ksqldb=lksqlc-1", "ksqldb", "lksqlc-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/flink=lfcp-1/statement=stmt-1", "statement", "stmt-1"),
        ("crn://confluent.cloud/organization=o-1/environment=env-1/compute-pool=lfcp-1", "compute_pool", "lfcp-1"),
    ],
)
def test_extract_resource_context_common_confluent_resources(crn, expected_type, expected_name):
    context = extract_resource_context({"resourceName": crn})
    assert context.resource_type == expected_type
    assert context.resource_name == expected_name
    assert context.resource_display_name.endswith(expected_name)
    assert context.resource_id == crn


def test_canonical_resource_type_covers_acl_rbac():
    assert canonical_resource_type("ACL / RBAC") == "role_binding"
    assert resource_type_label("role_binding") == "Role Binding"


def test_extract_resource_context_for_flink_statement():
    payload = {
        "cloudResources": {
            "scope": {
                "resources": [
                    {"resourceType": "ORGANIZATION", "resourceId": "org-1"},
                    {"resourceType": "ENVIRONMENT", "resourceId": "env-mkr6ww"},
                    {"resourceType": "FLINK_REGION", "resourceId": "aws.us-east-1"},
                ]
            },
            "resource": {"resourceType": "STATEMENT", "resourceId": "c360-loyalty-revenue-job"},
        }
    }
    context = extract_resource_context(payload)
    assert context.resource_type == "statement"
    assert context.resource_name == "c360-loyalty-revenue-job"
    assert context.resource_display_name == "Statement: c360-loyalty-revenue-job"
    assert context.environment_id == "env-mkr6ww"
    assert context.parent_resource == "environment:env-mkr6ww"
    assert context.resource_scope.startswith("environment:env-mkr6ww")
    assert context.resource_criticality == "medium"
    assert context.blast_radius_hint == "environment-scoped"
    assert context.production_hint == "unknown"


def test_extract_resource_context_for_topic_crn():
    payload = {
        "resourceName": "crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1/topic=orders"
    }
    context = extract_resource_context(payload)
    assert context.resource_type == "topic"
    assert context.resource_name == "orders"
    assert context.cluster_id == "lkc-1"
    assert context.environment_id == "env-1"
    assert context.resource_display_name == "Topic: orders"
    assert context.resource_scope == "environment:env-1 > cluster:lkc-1 > topic"
    assert context.resource_id == "crn://confluent.cloud/organization=o-1/environment=env-1/kafka=lkc-1/topic=orders"


def test_canonical_resource_type_supports_ksqldb():
    assert canonical_resource_type("KSQLDB") == "ksqldb"
    assert resource_type_label("ksqldb") == "KSQLDB"


def test_extract_resource_context_for_create_api_key():
    # CreateAPIKey cloudResources is a list; first item has USER scope (2 resources),
    # second has ENVIRONMENT + KAFKA_CLUSTER scope (4 resources). We should pick
    # the richer item and extract the key ID, cluster, and environment.
    payload = {
        "methodName": "CreateAPIKey",
        "resourceName": "crn://confluent.cloud/organization=f5f511c7-d821-48cc-8388-c96a6f11f12a",
        "cloudResources": [
            {
                "scope": {"resources": [
                    {"type": "ORGANIZATION", "resourceId": "f5f511c7-d821-48cc-8388-c96a6f11f12a"},
                    {"type": "USER", "resourceId": "u-12g806"},
                ]},
                "resource": {"type": "API_KEY", "resourceId": "76NATGA2SWTNEZX5"},
            },
            {
                "scope": {"resources": [
                    {"type": "ORGANIZATION", "resourceId": "f5f511c7-d821-48cc-8388-c96a6f11f12a"},
                    {"type": "ENVIRONMENT", "resourceId": "env-9zj7y5"},
                    {"type": "CLOUD_CLUSTER", "resourceId": "lkc-jqn0xm"},
                    {"type": "KAFKA_CLUSTER", "resourceId": "lkc-jqn0xm"},
                ]},
                "resource": {"type": "API_KEY", "resourceId": "76NATGA2SWTNEZX5"},
            },
        ],
    }
    context = extract_resource_context(payload)
    assert context.resource_type == "api_key"
    assert context.resource_name == "76NATGA2SWTNEZX5"
    assert "76NATGA2SWTNEZX5" in context.resource_display_name
    assert context.cluster_id == "lkc-jqn0xm"
    assert context.environment_id == "env-9zj7y5"
