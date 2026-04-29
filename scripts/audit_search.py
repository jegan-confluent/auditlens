#!/usr/bin/env python3
"""
Confluent Audit Log Search Tool

Simple CLI to answer: Who did what, when?

Usage:
    python audit_search.py --question "who deleted topics"
    python audit_search.py --user "john@company.com"
    python audit_search.py --action "Delete"
    python audit_search.py --ip "10.0.1.100"
    python audit_search.py --failures
"""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from confluent_kafka import Consumer, KafkaError


def parse_crn(crn: str) -> Dict[str, str]:
    """Extract components from Confluent Resource Name."""
    result = {}
    if not crn or not crn.startswith("crn://"):
        return result

    # Extract organization
    org_match = re.search(r'organization=([^/]+)', crn)
    if org_match:
        result['organization_id'] = org_match.group(1)

    # Extract environment
    env_match = re.search(r'environment=([^/]+)', crn)
    if env_match:
        result['environment_id'] = env_match.group(1)

    # Extract cluster
    for cluster_type in ['kafka', 'schema-registry', 'ksqldb', 'flink', 'connect']:
        match = re.search(f'{cluster_type}=([^/]+)', crn)
        if match:
            result['cluster_type'] = cluster_type
            result['cluster_id'] = match.group(1)
            break

    return result


def format_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Format audit event for display."""
    data = event.get('data', {})
    auth_info = data.get('authenticationInfo', {})
    result_info = data.get('result', {})
    request_meta = data.get('requestMetadata', {})

    crn_parts = parse_crn(event.get('source', ''))

    return {
        'time': event.get('time', 'N/A'),
        'who': auth_info.get('principal', 'N/A'),
        'action': data.get('methodName', 'N/A'),
        'event_type': event.get('type', 'N/A').split('/')[-1],
        'status': result_info.get('status', 'N/A'),
        'cluster_id': crn_parts.get('cluster_id', 'N/A'),
        'ip_address': request_meta.get('clientAddress', 'N/A'),
        'message': result_info.get('message', ''),
    }


def matches_filter(event: Dict[str, Any],
                   user: Optional[str] = None,
                   action: Optional[str] = None,
                   ip: Optional[str] = None,
                   failures_only: bool = False,
                   question: Optional[str] = None) -> bool:
    """Check if event matches filter criteria."""
    data = event.get('data', {})
    auth_info = data.get('authenticationInfo', {})
    result_info = data.get('result', {})
    request_meta = data.get('requestMetadata', {})
    method_name = data.get('methodName', '')
    principal = auth_info.get('principal', '')
    status = result_info.get('status', '')
    client_ip = request_meta.get('clientAddress', '')

    # Filter by user
    if user and user.lower() not in principal.lower():
        return False

    # Filter by action
    if action and action.lower() not in method_name.lower():
        return False

    # Filter by IP
    if ip and ip not in client_ip:
        return False

    # Filter failures only
    if failures_only and status == 'SUCCESS':
        return False

    # Natural language question parsing
    if question:
        q = question.lower()

        # "who deleted X"
        if 'delete' in q and 'Delete' not in method_name:
            return False

        # "who created X"
        if 'create' in q and 'Create' not in method_name:
            return False

        # Topic operations
        if 'topic' in q and 'Topic' not in method_name:
            return False

        # Cluster operations
        if 'cluster' in q and 'Cluster' not in method_name:
            return False

        # Connector operations
        if 'connector' in q and 'Connector' not in method_name:
            return False

        # API key operations
        if 'api key' in q and 'ApiKey' not in method_name:
            return False

        # Authentication failures
        if 'login' in q or 'auth' in q:
            event_type = event.get('type', '')
            if 'authentication' not in event_type.lower():
                return False

        # Failed operations
        if 'fail' in q and status == 'SUCCESS':
            return False

    return True


def search_audit_logs(bootstrap_servers: str,
                      api_key: str,
                      api_secret: str,
                      topic: str = 'confluent-audit-log-events',
                      hours_back: int = 24,
                      limit: int = 100,
                      **filters) -> List[Dict[str, Any]]:
    """Search audit logs from Kafka topic."""

    config = {
        'bootstrap.servers': bootstrap_servers,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': api_key,
        'sasl.password': api_secret,
        'group.id': f'audit-search-{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    }

    consumer = Consumer(config)
    consumer.subscribe([topic])

    results = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    print(f"Searching audit logs from last {hours_back} hours...")
    print(f"Filters: {filters}")
    print("-" * 60)

    try:
        empty_polls = 0
        while len(results) < limit and empty_polls < 10:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                empty_polls += 1
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    empty_polls += 1
                    continue
                print(f"Error: {msg.error()}")
                continue

            empty_polls = 0

            try:
                event = json.loads(msg.value().decode('utf-8'))

                # Check time filter
                event_time_str = event.get('time', '')
                if event_time_str:
                    try:
                        event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
                        if event_time.replace(tzinfo=None) < start_time:
                            continue
                    except ValueError:
                        pass

                # Apply filters
                if matches_filter(event, **filters):
                    results.append(format_event(event))

            except json.JSONDecodeError:
                continue

    finally:
        consumer.close()

    return results


def print_results(results: List[Dict[str, Any]]):
    """Print results in a readable format."""
    if not results:
        print("\nNo matching events found.")
        return

    print(f"\nFound {len(results)} matching events:\n")
    print("=" * 100)

    for i, event in enumerate(results, 1):
        print(f"\n[{i}] {event['time']}")
        print(f"    WHO:    {event['who']}")
        print(f"    ACTION: {event['action']}")
        print(f"    STATUS: {event['status']}")
        print(f"    CLUSTER: {event['cluster_id']}")
        print(f"    IP:     {event['ip_address']}")
        if event['message']:
            print(f"    MSG:    {event['message']}")
        print("-" * 100)


def main():
    parser = argparse.ArgumentParser(
        description='Search Confluent Cloud Audit Logs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --question "who deleted topics"
    %(prog)s --user "john@company.com"
    %(prog)s --action "DeleteKafkaCluster"
    %(prog)s --ip "10.0.1.100"
    %(prog)s --failures
    %(prog)s --question "who created api keys" --hours 168
        """
    )

    parser.add_argument('--question', '-q',
                        help='Natural language question (e.g., "who deleted topics")')
    parser.add_argument('--user', '-u',
                        help='Filter by user/principal')
    parser.add_argument('--action', '-a',
                        help='Filter by action/method name')
    parser.add_argument('--ip',
                        help='Filter by IP address')
    parser.add_argument('--failures', '-f', action='store_true',
                        help='Show only failed operations')
    parser.add_argument('--hours', type=int, default=24,
                        help='Hours to look back (default: 24)')
    parser.add_argument('--limit', type=int, default=100,
                        help='Maximum results (default: 100)')

    # Connection settings
    parser.add_argument('--bootstrap',
                        default=os.environ.get('AUDIT_BOOTSTRAP'),
                        help='Kafka bootstrap servers (or set AUDIT_BOOTSTRAP)')
    parser.add_argument('--api-key',
                        default=os.environ.get('AUDIT_API_KEY'),
                        help='API key (or set AUDIT_API_KEY)')
    parser.add_argument('--api-secret',
                        default=os.environ.get('AUDIT_API_SECRET'),
                        help='API secret (or set AUDIT_API_SECRET)')
    parser.add_argument('--topic', default='confluent-audit-log-events',
                        help='Audit log topic name')

    args = parser.parse_args()

    # Validate connection settings
    if not all([args.bootstrap, args.api_key, args.api_secret]):
        print("ERROR: Missing connection settings.")
        print("Set environment variables or provide --bootstrap, --api-key, --api-secret")
        print("\nExample:")
        print("  export AUDIT_BOOTSTRAP=pkc-xxxxx.region.aws.confluent.cloud:9092")
        print("  export AUDIT_API_KEY=your-api-key")
        print("  export AUDIT_API_SECRET=your-api-secret")
        return 1

    # Search
    results = search_audit_logs(
        bootstrap_servers=args.bootstrap,
        api_key=args.api_key,
        api_secret=args.api_secret,
        topic=args.topic,
        hours_back=args.hours,
        limit=args.limit,
        user=args.user,
        action=args.action,
        ip=args.ip,
        failures_only=args.failures,
        question=args.question
    )

    # Display
    print_results(results)

    return 0


if __name__ == '__main__':
    exit(main())
