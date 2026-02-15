#!/usr/bin/env python3
"""
Confluent Audit Log Report Generator

Generate compliance/security reports from audit logs.

Usage:
    python audit_report.py --report security --days 7
    python audit_report.py --report changes --days 30
    python audit_report.py --report access --days 7
"""

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any

from confluent_kafka import Consumer, KafkaError


def parse_crn(crn: str) -> Dict[str, str]:
    """Extract components from CRN."""
    result = {}
    if not crn:
        return result

    for pattern, key in [
        (r'organization=([^/]+)', 'org'),
        (r'environment=([^/]+)', 'env'),
        (r'kafka=([^/]+)', 'cluster'),
        (r'schema-registry=([^/]+)', 'cluster'),
        (r'connect=([^/]+)', 'cluster'),
    ]:
        match = re.search(pattern, crn)
        if match:
            result[key] = match.group(1)

    return result


def consume_audit_logs(bootstrap: str, api_key: str, api_secret: str,
                       topic: str, days: int) -> List[Dict]:
    """Consume audit logs from Kafka."""
    config = {
        'bootstrap.servers': bootstrap,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': api_key,
        'sasl.password': api_secret,
        'group.id': f'audit-report-{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    }

    consumer = Consumer(config)
    consumer.subscribe([topic])

    events = []
    cutoff = datetime.utcnow() - timedelta(days=days)

    print(f"Loading audit logs from last {days} days...")

    try:
        empty_polls = 0
        while empty_polls < 20:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                empty_polls += 1
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    empty_polls += 1
                continue

            empty_polls = 0

            try:
                event = json.loads(msg.value().decode('utf-8'))
                events.append(event)
            except json.JSONDecodeError:
                continue

    finally:
        consumer.close()

    print(f"Loaded {len(events)} events")
    return events


def generate_security_report(events: List[Dict]) -> str:
    """Generate security-focused report."""
    auth_failures = []
    authz_denials = []
    transparency_events = []
    suspicious_ips = defaultdict(list)

    for event in events:
        data = event.get('data', {})
        event_type = event.get('type', '')
        result = data.get('result', {})
        status = result.get('status', '')
        principal = data.get('authenticationInfo', {}).get('principal', 'Unknown')
        ip = data.get('requestMetadata', {}).get('clientAddress', 'Unknown')
        time = event.get('time', 'Unknown')

        # Authentication failures
        if 'authentication' in event_type and status == 'UNAUTHENTICATED':
            auth_failures.append({
                'time': time,
                'principal': principal,
                'ip': ip,
                'message': result.get('message', '')
            })
            suspicious_ips[ip].append(('AUTH_FAILURE', time, principal))

        # Authorization denials
        if 'authorization' in event_type and status == 'PERMISSION_DENIED':
            authz_info = data.get('authorizationInfo', {})
            authz_denials.append({
                'time': time,
                'principal': principal,
                'resource': f"{authz_info.get('resourceType', '')}:{authz_info.get('resourceName', '')}",
                'operation': authz_info.get('operation', ''),
                'ip': ip
            })
            suspicious_ips[ip].append(('AUTHZ_DENIAL', time, principal))

        # Access transparency
        if 'access-transparency' in event_type:
            transparency = data.get('accessTransparency', {})
            transparency_events.append({
                'time': time,
                'accessed_by': transparency.get('accessedBy', principal),
                'reason': transparency.get('reason', ''),
                'case': transparency.get('caseNumber', '')
            })

    # Build report
    report = []
    report.append("=" * 80)
    report.append("SECURITY AUDIT REPORT")
    report.append(f"Generated: {datetime.now().isoformat()}")
    report.append("=" * 80)

    # Authentication Failures
    report.append(f"\n## AUTHENTICATION FAILURES ({len(auth_failures)} events)")
    report.append("-" * 40)
    if auth_failures:
        for f in auth_failures[:20]:
            report.append(f"  {f['time']} | {f['principal']} | IP: {f['ip']}")
        if len(auth_failures) > 20:
            report.append(f"  ... and {len(auth_failures) - 20} more")
    else:
        report.append("  None")

    # Authorization Denials
    report.append(f"\n## AUTHORIZATION DENIALS ({len(authz_denials)} events)")
    report.append("-" * 40)
    if authz_denials:
        for d in authz_denials[:20]:
            report.append(f"  {d['time']} | {d['principal']}")
            report.append(f"    Tried: {d['operation']} on {d['resource']}")
        if len(authz_denials) > 20:
            report.append(f"  ... and {len(authz_denials) - 20} more")
    else:
        report.append("  None")

    # Suspicious IPs
    report.append(f"\n## SUSPICIOUS IP ADDRESSES")
    report.append("-" * 40)
    suspicious = [(ip, events) for ip, events in suspicious_ips.items() if len(events) >= 3]
    if suspicious:
        for ip, ip_events in sorted(suspicious, key=lambda x: -len(x[1]))[:10]:
            report.append(f"  {ip}: {len(ip_events)} security events")
    else:
        report.append("  None (threshold: 3+ events)")

    # Access Transparency
    report.append(f"\n## CONFLUENT PERSONNEL ACCESS ({len(transparency_events)} events)")
    report.append("-" * 40)
    if transparency_events:
        for t in transparency_events:
            report.append(f"  {t['time']}")
            report.append(f"    By: {t['accessed_by']}")
            report.append(f"    Reason: {t['reason']}")
            if t['case']:
                report.append(f"    Case: {t['case']}")
    else:
        report.append("  None")

    return "\n".join(report)


def generate_changes_report(events: List[Dict]) -> str:
    """Generate infrastructure changes report."""
    creates = defaultdict(list)
    deletes = defaultdict(list)
    updates = defaultdict(list)

    for event in events:
        data = event.get('data', {})
        event_type = event.get('type', '')

        if 'request' not in event_type:
            continue

        method = data.get('methodName', '')
        principal = data.get('authenticationInfo', {}).get('principal', 'Unknown')
        time = event.get('time', 'Unknown')
        status = data.get('result', {}).get('status', '')
        source = event.get('source', '')
        crn = parse_crn(source)

        if status != 'SUCCESS':
            continue

        entry = {
            'time': time,
            'who': principal,
            'cluster': crn.get('cluster', 'N/A'),
            'method': method
        }

        if 'Create' in method:
            resource_type = method.replace('Create', '').replace('kafka.', '')
            creates[resource_type].append(entry)
        elif 'Delete' in method:
            resource_type = method.replace('Delete', '').replace('kafka.', '')
            deletes[resource_type].append(entry)
        elif 'Update' in method or 'Alter' in method:
            resource_type = method.replace('Update', '').replace('Alter', '').replace('kafka.', '')
            updates[resource_type].append(entry)

    # Build report
    report = []
    report.append("=" * 80)
    report.append("INFRASTRUCTURE CHANGES REPORT")
    report.append(f"Generated: {datetime.now().isoformat()}")
    report.append("=" * 80)

    # Deletions (most important)
    report.append("\n## DELETIONS (Review Carefully!)")
    report.append("-" * 40)
    if deletes:
        for resource_type, items in sorted(deletes.items()):
            report.append(f"\n  {resource_type}: {len(items)} deleted")
            for item in items[:5]:
                report.append(f"    {item['time']} by {item['who']}")
            if len(items) > 5:
                report.append(f"    ... and {len(items) - 5} more")
    else:
        report.append("  None")

    # Creations
    report.append("\n## CREATIONS")
    report.append("-" * 40)
    if creates:
        for resource_type, items in sorted(creates.items()):
            report.append(f"\n  {resource_type}: {len(items)} created")
            for item in items[:5]:
                report.append(f"    {item['time']} by {item['who']}")
            if len(items) > 5:
                report.append(f"    ... and {len(items) - 5} more")
    else:
        report.append("  None")

    # Updates
    report.append("\n## MODIFICATIONS")
    report.append("-" * 40)
    if updates:
        for resource_type, items in sorted(updates.items()):
            report.append(f"\n  {resource_type}: {len(items)} modified")
            for item in items[:5]:
                report.append(f"    {item['time']} by {item['who']}")
            if len(items) > 5:
                report.append(f"    ... and {len(items) - 5} more")
    else:
        report.append("  None")

    return "\n".join(report)


def generate_access_report(events: List[Dict]) -> str:
    """Generate user access report."""
    user_activity = defaultdict(lambda: {
        'first_seen': None,
        'last_seen': None,
        'actions': defaultdict(int),
        'clusters': set(),
        'ips': set()
    })

    for event in events:
        data = event.get('data', {})
        principal = data.get('authenticationInfo', {}).get('principal', '')
        if not principal:
            continue

        time = event.get('time', '')
        method = data.get('methodName', 'Unknown')
        source = event.get('source', '')
        ip = data.get('requestMetadata', {}).get('clientAddress', '')
        crn = parse_crn(source)

        user = user_activity[principal]

        if not user['first_seen'] or time < user['first_seen']:
            user['first_seen'] = time
        if not user['last_seen'] or time > user['last_seen']:
            user['last_seen'] = time

        user['actions'][method] += 1
        if crn.get('cluster'):
            user['clusters'].add(crn['cluster'])
        if ip:
            user['ips'].add(ip)

    # Build report
    report = []
    report.append("=" * 80)
    report.append("USER ACCESS REPORT")
    report.append(f"Generated: {datetime.now().isoformat()}")
    report.append("=" * 80)

    report.append(f"\n## ACTIVE USERS ({len(user_activity)} total)")
    report.append("-" * 40)

    # Sort by activity
    sorted_users = sorted(
        user_activity.items(),
        key=lambda x: sum(x[1]['actions'].values()),
        reverse=True
    )

    for principal, activity in sorted_users[:30]:
        total_actions = sum(activity['actions'].values())
        report.append(f"\n  {principal}")
        report.append(f"    Total actions: {total_actions}")
        report.append(f"    First seen: {activity['first_seen']}")
        report.append(f"    Last seen: {activity['last_seen']}")
        report.append(f"    Clusters accessed: {len(activity['clusters'])}")
        report.append(f"    IPs used: {', '.join(list(activity['ips'])[:3])}")

        # Top actions
        top_actions = sorted(activity['actions'].items(), key=lambda x: -x[1])[:3]
        if top_actions:
            report.append(f"    Top actions: {', '.join([f'{a}({c})' for a, c in top_actions])}")

    if len(sorted_users) > 30:
        report.append(f"\n  ... and {len(sorted_users) - 30} more users")

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description='Generate Audit Log Reports')
    parser.add_argument('--report', '-r', required=True,
                        choices=['security', 'changes', 'access'],
                        help='Report type')
    parser.add_argument('--days', '-d', type=int, default=7,
                        help='Days to look back (default: 7)')
    parser.add_argument('--output', '-o',
                        help='Output file (default: stdout)')

    # Connection
    parser.add_argument('--bootstrap', default=os.environ.get('AUDIT_BOOTSTRAP'))
    parser.add_argument('--api-key', default=os.environ.get('AUDIT_API_KEY'))
    parser.add_argument('--api-secret', default=os.environ.get('AUDIT_API_SECRET'))
    parser.add_argument('--topic', default='confluent-audit-log-events')

    args = parser.parse_args()

    if not all([args.bootstrap, args.api_key, args.api_secret]):
        print("ERROR: Set AUDIT_BOOTSTRAP, AUDIT_API_KEY, AUDIT_API_SECRET")
        return 1

    # Load events
    events = consume_audit_logs(
        args.bootstrap, args.api_key, args.api_secret,
        args.topic, args.days
    )

    # Generate report
    if args.report == 'security':
        report = generate_security_report(events)
    elif args.report == 'changes':
        report = generate_changes_report(events)
    elif args.report == 'access':
        report = generate_access_report(events)

    # Output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)

    return 0


if __name__ == '__main__':
    exit(main())
