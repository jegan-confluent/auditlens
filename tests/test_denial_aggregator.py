"""Tests for denial aggregation bucketing and payload shape."""

from datetime import datetime, timezone

from src.aggregation.denial_aggregator import DenialAggregator, AggregatorConfig


def _event(principal: str, method: str, resource: str) -> dict:
    return {
        "id": f"{principal}-{method}-{resource}",
        "principal": principal,
        "principal_raw": principal,
        "principal_normalized": principal.replace("User:", ""),
        "principal_type": "service_account" if "sa-" in principal else "user",
        "methodName": method,
        "authzResourceName": resource,
        "resourceName": resource,
        "resourceType": "Topic",
        "operation": "READ",
        "granted": False,
        "resultStatus": "SUCCESS",
        "cluster_id": "lkc-123",
        "environment_id": "env-123",
        "organization_id": "org-123",
    }


def test_denials_group_by_principal_method_resource():
    agg = DenialAggregator(config=AggregatorConfig(enabled=True, dry_run=True, window_seconds=3600))
    agg.add_event(_event("User:sa-1", "mds.Authorize", "topic-a"))
    agg.add_event(_event("User:sa-1", "mds.Authorize", "topic-a"))
    agg.add_event(_event("User:sa-1", "mds.Authorize", "topic-b"))

    assert len(agg._buckets) == 2

    bucket = agg._buckets[("sa-1", "mds.Authorize", "topic-a")]
    assert bucket.denial_count == 2
    agg.shutdown()


def test_denial_alert_contains_normalized_principal_and_resource():
    agg = DenialAggregator(config=AggregatorConfig(enabled=True, dry_run=True, window_seconds=3600))
    agg.add_event(_event("User:sa-1", "mds.Authorize", "topic-a"))
    bucket = next(iter(agg._buckets.values()))
    alert = agg._create_alert(bucket, datetime.now(timezone.utc))
    payload = alert.to_dict()

    assert payload["principal_raw"] == "User:sa-1"
    assert payload["principal_normalized"] == "sa-1"
    assert payload["principal_type"] == "service_account"
    assert payload["resource_name"] == "topic-a"
    assert payload["methodName"] == "mds.Authorize"
    agg.shutdown()
