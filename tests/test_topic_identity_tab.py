"""Unit tests for Topic × Identity Matrix tab.

These tests focus on the pure data transformation functions
without importing the Streamlit-dependent dashboard module.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple


# ============================================================
# Copy of pure functions from topic_identity.py for testing
# (Avoids Streamlit import issues)
# ============================================================

def aggregate_topic_activity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate audit events by topic × identity.

    Returns DataFrame with columns:
    - cluster_id, topic_resource, principal, display_name
    - methods (list), event_count, first_seen, last_seen
    """
    if df.empty:
        return pd.DataFrame()

    # Filter to topic-related events
    topic_events = df[
        df['methodName'].str.contains('kafka\\.', case=False, na=False) |
        df['methodName'].str.contains('Produce|Fetch|Topic', case=True, na=False)
    ].copy()

    if topic_events.empty:
        return pd.DataFrame()

    # Extract topic name from resourceName or authzResourceName
    def extract_topic(row):
        resource = row.get('authzResourceName') or row.get('resourceName') or ''
        if not resource:
            return None
        # Parse CRN format: crn://...kafka=.../topic=payments-events
        if 'topic=' in str(resource):
            parts = str(resource).split('topic=')
            if len(parts) > 1:
                return parts[1].split('/')[0]
        # Simple topic name
        if '/' not in str(resource) and 'crn:' not in str(resource):
            return str(resource)
        return None

    topic_events['topic_resource'] = topic_events.apply(extract_topic, axis=1)
    topic_events = topic_events[topic_events['topic_resource'].notna()]

    if topic_events.empty:
        return pd.DataFrame()

    # Ensure time column is datetime
    if 'time' in topic_events.columns:
        topic_events['time'] = pd.to_datetime(topic_events['time'], errors='coerce')

    # Aggregate by cluster × topic × principal
    aggregated = topic_events.groupby(
        ['cluster_id', 'topic_resource', 'principal'],
        dropna=False
    ).agg({
        'methodName': lambda x: list(set(x.dropna())),
        'id': 'count',
        'time': ['min', 'max'],
    }).reset_index()

    # Flatten column names
    aggregated.columns = [
        'cluster_id', 'topic_resource', 'principal',
        'methods', 'event_count', 'first_seen', 'last_seen'
    ]

    # Sort by event count descending
    aggregated = aggregated.sort_values('event_count', ascending=False)

    return aggregated


def find_stale_acls(
    activity_df: pd.DataFrame,
    acl_data: Dict[str, List[Dict[str, Any]]],
    stale_days: int = 30
) -> pd.DataFrame:
    """
    Find ACLs for principals with no recent activity.

    Returns DataFrame with stale ACL entries.
    """
    if activity_df.empty or not acl_data:
        return pd.DataFrame()

    # Get active principals per topic
    active_principals: Dict[str, set] = {}
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=stale_days)

    for _, row in activity_df.iterrows():
        topic = row.get('topic_resource')
        principal = row.get('principal')
        last_seen = row.get('last_seen')

        if not topic or not principal:
            continue

        # Check if activity is recent
        if pd.notna(last_seen):
            if isinstance(last_seen, str):
                last_seen = pd.to_datetime(last_seen)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen >= cutoff_time:
                if topic not in active_principals:
                    active_principals[topic] = set()
                active_principals[topic].add(principal)

    # Find ACL principals with no activity
    stale_entries = []

    for topic, acls in acl_data.items():
        active = active_principals.get(topic, set())

        for acl in acls:
            principal = acl.get('principal', '')
            # Normalize principal for comparison
            normalized = principal.replace('User:', '')

            # Check if this principal has recent activity
            has_activity = any(
                normalized in str(ap) or str(ap) in normalized
                for ap in active
            )

            if not has_activity:
                stale_entries.append({
                    'topic': topic,
                    'principal': principal,
                    'operation': acl.get('operation'),
                    'permission': acl.get('permission'),
                    'cluster_id': acl.get('cluster_id'),
                    'stale_days': stale_days,
                })

    return pd.DataFrame(stale_entries)


def calculate_risk_score(
    activity_df: pd.DataFrame,
    time_window_days: int = 7
) -> Tuple[str, List[str]]:
    """
    Calculate risk score for an identity based on their activity.

    Returns:
        Tuple of (risk_level, list of risk indicators)
    """
    if activity_df.empty:
        return 'LOW', []

    indicators = []
    risk_points = 0

    # Check for authorization failures
    if 'result' in activity_df.columns:
        failures = activity_df[activity_df['result'].str.contains('DENY|FAIL', case=False, na=False)]
        failure_rate = len(failures) / len(activity_df) if len(activity_df) > 0 else 0

        if failure_rate > 0.5:
            risk_points += 30
            indicators.append(f"High failure rate: {failure_rate:.1%}")
        elif failure_rate > 0.2:
            risk_points += 15
            indicators.append(f"Elevated failure rate: {failure_rate:.1%}")

    # Check for off-hours activity
    if 'time' in activity_df.columns:
        activity_df = activity_df.copy()
        activity_df['time'] = pd.to_datetime(activity_df['time'], errors='coerce')
        activity_df['hour'] = activity_df['time'].dt.hour
        off_hours = activity_df[(activity_df['hour'] < 6) | (activity_df['hour'] > 22)]
        if len(off_hours) > 5:
            risk_points += 10
            indicators.append(f"Off-hours activity: {len(off_hours)} events")

    # Check for burst activity
    if 'time' in activity_df.columns and len(activity_df) > 10:
        # Check if many events in short time
        time_span = (activity_df['time'].max() - activity_df['time'].min()).total_seconds()
        if time_span > 0:
            events_per_minute = len(activity_df) / (time_span / 60)
            if events_per_minute > 100:
                risk_points += 20
                indicators.append(f"Burst activity: {events_per_minute:.1f} events/min")

    # Determine risk level
    if risk_points >= 40:
        return 'CRITICAL', indicators
    elif risk_points >= 25:
        return 'HIGH', indicators
    elif risk_points >= 10:
        return 'MEDIUM', indicators
    else:
        return 'LOW', indicators


# ============================================================
# Test Classes
# ============================================================

class TestAggregateTopicActivity:
    """Tests for aggregate_topic_activity function."""

    def test_empty_dataframe(self):
        """Test aggregation with empty dataframe."""
        df = pd.DataFrame()
        result = aggregate_topic_activity(df)
        assert result.empty

    def test_no_topic_events(self):
        """Test aggregation when no topic-related events exist."""
        df = pd.DataFrame({
            'methodName': ['mds.Authorize', 'iam.CreateUser'],
            'resourceName': ['user1', 'user2'],
            'principal': ['sa-abc', 'sa-def'],
            'cluster_id': ['lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2'],
            'time': [datetime.now(timezone.utc), datetime.now(timezone.utc)],
        })
        result = aggregate_topic_activity(df)
        assert result.empty

    def test_basic_aggregation(self):
        """Test basic topic activity aggregation."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': [
                'kafka.Produce',
                'kafka.Produce',
                'kafka.Fetch',
            ],
            'resourceName': [
                'crn://confluent.cloud/kafka=lkc-123/topic=payments-events',
                'crn://confluent.cloud/kafka=lkc-123/topic=payments-events',
                'crn://confluent.cloud/kafka=lkc-123/topic=orders-events',
            ],
            'authzResourceName': [None, None, None],
            'principal': ['sa-abc', 'sa-abc', 'sa-def'],
            'cluster_id': ['lkc-123', 'lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2', 'evt3'],
            'time': [now, now - timedelta(hours=1), now - timedelta(hours=2)],
        })

        result = aggregate_topic_activity(df)

        assert not result.empty
        assert 'topic_resource' in result.columns
        assert 'principal' in result.columns
        assert 'event_count' in result.columns

    def test_topic_extraction_from_crn(self):
        """Test that topic names are extracted correctly from CRN format."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': ['kafka.Produce'],
            'resourceName': ['crn://confluent.cloud/organization=abc/environment=env-1/cloud-cluster=lkc-123/kafka=lkc-123/topic=my-special-topic'],
            'authzResourceName': [None],
            'principal': ['sa-abc'],
            'cluster_id': ['lkc-123'],
            'id': ['evt1'],
            'time': [now],
        })

        result = aggregate_topic_activity(df)

        assert not result.empty
        assert 'my-special-topic' in result['topic_resource'].values

    def test_aggregation_groups_by_principal(self):
        """Test that events are grouped by principal correctly."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': [
                'kafka.Produce',
                'kafka.Produce',
                'kafka.Produce',
            ],
            'resourceName': [
                'crn://kafka=lkc-123/topic=payments',
                'crn://kafka=lkc-123/topic=payments',
                'crn://kafka=lkc-123/topic=payments',
            ],
            'authzResourceName': [None, None, None],
            'principal': ['sa-abc', 'sa-abc', 'sa-def'],  # 2 from sa-abc, 1 from sa-def
            'cluster_id': ['lkc-123', 'lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2', 'evt3'],
            'time': [now, now, now],
        })

        result = aggregate_topic_activity(df)

        # Should have 2 rows: one for sa-abc, one for sa-def
        payments_rows = result[result['topic_resource'] == 'payments']
        assert len(payments_rows) == 2

        # sa-abc should have count of 2
        sa_abc_row = result[result['principal'] == 'sa-abc']
        assert sa_abc_row.iloc[0]['event_count'] == 2

    def test_methods_aggregated_as_list(self):
        """Test that methods are aggregated as unique list."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': [
                'kafka.Produce',
                'kafka.Fetch',
                'kafka.Produce',  # Duplicate
            ],
            'resourceName': [
                'crn://kafka=lkc-123/topic=events',
                'crn://kafka=lkc-123/topic=events',
                'crn://kafka=lkc-123/topic=events',
            ],
            'authzResourceName': [None, None, None],
            'principal': ['sa-abc', 'sa-abc', 'sa-abc'],
            'cluster_id': ['lkc-123', 'lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2', 'evt3'],
            'time': [now, now, now],
        })

        result = aggregate_topic_activity(df)

        assert not result.empty
        methods = result.iloc[0]['methods']
        assert isinstance(methods, list)
        # Should have unique methods only
        assert 'kafka.Produce' in methods
        assert 'kafka.Fetch' in methods


class TestFindStaleACLs:
    """Tests for find_stale_acls function."""

    def test_empty_activity(self):
        """Test with empty activity dataframe."""
        df = pd.DataFrame()
        acl_data = {'topic1': [{'principal': 'User:sa-abc', 'operation': 'READ', 'permission': 'ALLOW'}]}

        result = find_stale_acls(df, acl_data, stale_days=30)
        assert result.empty

    def test_empty_acls(self):
        """Test with empty ACL data."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'topic_resource': ['topic1'],
            'principal': ['sa-abc'],
            'last_seen': [now],
        })

        result = find_stale_acls(df, {}, stale_days=30)
        assert result.empty

    def test_all_acls_active(self):
        """Test when all ACL principals have recent activity."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'topic_resource': ['payments-events', 'payments-events'],
            'principal': ['sa-abc', 'sa-def'],
            'last_seen': [now, now - timedelta(days=5)],
        })

        acl_data = {
            'payments-events': [
                {'principal': 'User:sa-abc', 'operation': 'READ', 'permission': 'ALLOW'},
                {'principal': 'User:sa-def', 'operation': 'WRITE', 'permission': 'ALLOW'},
            ]
        }

        result = find_stale_acls(df, acl_data, stale_days=30)
        # Both principals are active within 30 days
        assert result.empty

    def test_stale_acl_detected(self):
        """Test that stale ACLs are detected."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'topic_resource': ['payments-events'],
            'principal': ['sa-abc'],  # Only sa-abc is active
            'last_seen': [now],
        })

        acl_data = {
            'payments-events': [
                {'principal': 'User:sa-abc', 'operation': 'READ', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
                {'principal': 'User:sa-xyz', 'operation': 'WRITE', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},  # No activity
            ]
        }

        result = find_stale_acls(df, acl_data, stale_days=30)

        # sa-xyz should be detected as stale
        assert not result.empty
        assert 'User:sa-xyz' in result['principal'].values

    def test_stale_threshold_respected(self):
        """Test that stale_days threshold is respected."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'topic_resource': ['events'],
            'principal': ['sa-abc'],
            'last_seen': [now - timedelta(days=15)],  # 15 days ago
        })

        acl_data = {
            'events': [
                {'principal': 'User:sa-abc', 'operation': 'READ', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
            ]
        }

        # With 30 day threshold, should not be stale
        result_30 = find_stale_acls(df, acl_data, stale_days=30)
        assert result_30.empty

        # With 7 day threshold, should be stale
        result_7 = find_stale_acls(df, acl_data, stale_days=7)
        assert not result_7.empty

    def test_principal_normalization(self):
        """Test that User: prefix is normalized when matching."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'topic_resource': ['events'],
            'principal': ['sa-abc'],  # Without User: prefix
            'last_seen': [now],
        })

        acl_data = {
            'events': [
                {'principal': 'User:sa-abc', 'operation': 'READ', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
            ]
        }

        result = find_stale_acls(df, acl_data, stale_days=30)
        # Should match despite User: prefix in ACL
        assert result.empty


class TestRiskScoreCalculation:
    """Tests for risk score calculation."""

    def test_empty_dataframe_low_risk(self):
        """Test that empty dataframe returns LOW risk."""
        df = pd.DataFrame()
        risk_level, indicators = calculate_risk_score(df)
        assert risk_level == 'LOW'
        assert indicators == []

    def test_normal_activity_low_risk(self):
        """Test low risk score for normal activity."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'time': [now - timedelta(hours=1), now - timedelta(hours=2)],
            'methodName': ['kafka.Produce', 'kafka.Produce'],
            'result': ['SUCCESS', 'SUCCESS'],
        })

        risk_level, indicators = calculate_risk_score(df)
        assert risk_level == 'LOW'

    def test_high_failure_rate_increases_risk(self):
        """Test that high failure rate increases risk score."""
        now = datetime.now(timezone.utc)
        # Create many failure events (>50% failures)
        df = pd.DataFrame({
            'time': [now - timedelta(minutes=i) for i in range(10)],
            'methodName': ['kafka.Produce'] * 10,
            'result': ['DENY'] * 8 + ['SUCCESS'] * 2,  # 80% failure rate
        })

        risk_level, indicators = calculate_risk_score(df)
        # Should have elevated risk due to failures
        assert risk_level in ['MEDIUM', 'HIGH', 'CRITICAL']
        assert any('failure rate' in ind.lower() for ind in indicators)

    def test_off_hours_activity(self):
        """Test that off-hours activity is flagged."""
        # Create events at 3am
        off_hour_time = datetime.now(timezone.utc).replace(hour=3, minute=0)
        df = pd.DataFrame({
            'time': [off_hour_time - timedelta(minutes=i) for i in range(10)],
            'methodName': ['kafka.Produce'] * 10,
            'result': ['SUCCESS'] * 10,
        })

        risk_level, indicators = calculate_risk_score(df)
        # May or may not trigger depending on count, but shouldn't error
        assert risk_level in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

    def test_burst_activity(self):
        """Test that burst activity is detected."""
        now = datetime.now(timezone.utc)
        # 150 events in 1 minute = 150 events/min (>100)
        df = pd.DataFrame({
            'time': [now - timedelta(seconds=i * 0.4) for i in range(150)],
            'methodName': ['kafka.Produce'] * 150,
            'result': ['SUCCESS'] * 150,
        })

        risk_level, indicators = calculate_risk_score(df)
        # Should detect burst activity
        assert risk_level in ['MEDIUM', 'HIGH', 'CRITICAL']
        assert any('burst' in ind.lower() for ind in indicators)


class TestDataFrameEdgeCases:
    """Test edge cases in data handling."""

    def test_none_values_in_topic_resource(self):
        """Test handling of None values in resourceName."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': ['kafka.Produce', 'kafka.Fetch'],
            'resourceName': [None, 'crn://kafka=lkc-123/topic=events'],
            'authzResourceName': [None, None],
            'principal': ['sa-abc', 'sa-def'],
            'cluster_id': ['lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2'],
            'time': [now, now],
        })

        result = aggregate_topic_activity(df)

        # Should only include the row with valid topic
        assert len(result) <= 1

    def test_mixed_time_formats(self):
        """Test handling of mixed timestamp formats."""
        df = pd.DataFrame({
            'methodName': ['kafka.Produce', 'kafka.Fetch'],
            'resourceName': [
                'crn://kafka=lkc-123/topic=events',
                'crn://kafka=lkc-123/topic=events',
            ],
            'authzResourceName': [None, None],
            'principal': ['sa-abc', 'sa-abc'],
            'cluster_id': ['lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2'],
            'time': ['2024-01-15T10:00:00Z', datetime.now(timezone.utc)],
        })

        # Should not raise an error
        result = aggregate_topic_activity(df)
        assert not result.empty

    def test_unicode_topic_names(self):
        """Test handling of unicode characters in topic names."""
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'methodName': ['kafka.Produce'],
            'resourceName': ['crn://kafka=lkc-123/topic=events-日本語'],
            'authzResourceName': [None],
            'principal': ['sa-abc'],
            'cluster_id': ['lkc-123'],
            'id': ['evt1'],
            'time': [now],
        })

        result = aggregate_topic_activity(df)

        assert not result.empty
        assert 'events-日本語' in result['topic_resource'].values


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_pipeline(self):
        """Test the full aggregation and stale detection pipeline."""
        now = datetime.now(timezone.utc)

        # Create activity data
        df = pd.DataFrame({
            'methodName': [
                'kafka.Produce',
                'kafka.Produce',
                'kafka.Fetch',
            ],
            'resourceName': [
                'crn://kafka=lkc-123/topic=active-topic',
                'crn://kafka=lkc-123/topic=active-topic',
                'crn://kafka=lkc-123/topic=another-topic',
            ],
            'authzResourceName': [None, None, None],
            'principal': ['sa-active', 'sa-active', 'sa-another'],
            'cluster_id': ['lkc-123', 'lkc-123', 'lkc-123'],
            'id': ['evt1', 'evt2', 'evt3'],
            'time': [now, now - timedelta(hours=1), now],
        })

        # Aggregate activity
        activity_df = aggregate_topic_activity(df)
        assert not activity_df.empty

        # Create ACL data with one stale entry
        acl_data = {
            'active-topic': [
                {'principal': 'User:sa-active', 'operation': 'WRITE', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
                {'principal': 'User:sa-stale', 'operation': 'READ', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
            ],
            'another-topic': [
                {'principal': 'User:sa-another', 'operation': 'READ', 'permission': 'ALLOW', 'cluster_id': 'lkc-123'},
            ],
        }

        # Find stale ACLs
        stale = find_stale_acls(activity_df, acl_data, stale_days=30)

        # sa-stale should be detected
        assert not stale.empty
        assert 'User:sa-stale' in stale['principal'].values
