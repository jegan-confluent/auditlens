#!/usr/bin/env python3
"""
Audit Log Query Tool
====================
Query flattened audit events from the destination topic using Python.
No need for Flink SQL - queries data directly from Kafka.

Usage:
    ./query.py                    # Interactive menu
    ./query.py --recent 20        # Last 20 events
    ./query.py --user user@email  # Events by user
    ./query.py --type Delete      # Events by type
"""

import json
import os
import sys
from datetime import datetime
from confluent_kafka import Consumer, KafkaError
from dotenv import load_dotenv

# Load environment
load_dotenv('.env')
load_dotenv('.secrets')

# Kafka config
BOOTSTRAP = os.getenv('DEST_BOOTSTRAP')
API_KEY = os.getenv('DEST_API_KEY')
API_SECRET = os.getenv('DEST_API_SECRET')
TOPIC = os.getenv('DEST_TOPIC', 'audit_events_flattened')

def get_consumer(group_id='audit-query-tool'):
    """Create Kafka consumer."""
    return Consumer({
        'bootstrap.servers': BOOTSTRAP,
        'security.protocol': 'SASL_SSL',
        'sasl.mechanisms': 'PLAIN',
        'sasl.username': API_KEY,
        'sasl.password': API_SECRET,
        'group.id': group_id,
        'auto.offset.reset': 'latest',
        'enable.auto.commit': False,
    })

def format_event(event, verbose=False):
    """Format event for display."""
    time_str = event.get('time', event.get('event_time', 'N/A'))
    if isinstance(time_str, str) and len(time_str) > 19:
        time_str = time_str[:19]

    principal = event.get('principal', event.get('principal_email', 'N/A'))
    if principal and len(principal) > 30:
        principal = principal[:27] + '...'

    method = event.get('methodName', event.get('method_name', 'N/A'))
    resource = event.get('resourceName', event.get('resource_name', 'N/A'))
    if resource and len(resource) > 40:
        resource = resource[:37] + '...'

    result = event.get('resultStatus', event.get('result_status', event.get('granted', 'N/A')))

    if verbose:
        return f"""
Time:       {time_str}
Principal:  {principal}
Method:     {method}
Resource:   {resource}
Result:     {result}
Type:       {event.get('type', event.get('event_type', 'N/A'))}
Client IP:  {event.get('clientIp', event.get('client_ip', 'N/A'))}
{'─' * 60}"""
    else:
        return f"{time_str}  {principal:30}  {method:30}  {result}"

def query_recent(limit=20, filter_func=None, verbose=False):
    """Query recent events from the topic."""
    from confluent_kafka import TopicPartition

    consumer = get_consumer(f'query-{datetime.now().timestamp()}')

    # Get partition info
    metadata = consumer.list_topics(TOPIC, timeout=10)
    if TOPIC not in metadata.topics:
        print(f"Topic {TOPIC} not found!")
        return []

    partitions = [TopicPartition(TOPIC, p) for p in metadata.topics[TOPIC].partitions]

    # Get watermarks and seek to recent offsets
    for tp in partitions:
        low, high = consumer.get_watermark_offsets(tp)
        # Start from near the end to get recent events
        start = max(low, high - (limit * 5 // len(partitions)))
        tp.offset = start

    consumer.assign(partitions)

    events = []
    empty_polls = 0
    max_empty = 5
    max_events = limit * 10  # Fetch more to filter

    print(f"\nFetching events from {TOPIC}...")

    while len(events) < max_events and empty_polls < max_empty:
        msg = consumer.poll(2.0)
        if msg is None:
            empty_polls += 1
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                print(f"Error: {msg.error()}")
            empty_polls += 1
            continue

        empty_polls = 0
        try:
            value = msg.value()
            if value:
                # Handle Schema Registry magic bytes (first 5 bytes are magic + schema ID)
                if len(value) > 5 and value[0] == 0:
                    # Skip the 5-byte header (magic byte + 4-byte schema ID)
                    json_data = value[5:]
                else:
                    json_data = value
                event = json.loads(json_data.decode('utf-8'))
                if filter_func is None or filter_func(event):
                    events.append(event)
        except Exception as e:
            pass

    consumer.close()

    # Sort by time and take latest
    events.sort(key=lambda x: x.get('time', x.get('event_time', '')), reverse=True)
    return events[:limit]

def print_events(events, verbose=False):
    """Print events."""
    if not events:
        print("\nNo events found.")
        return

    if not verbose:
        print(f"\n{'Time':19}  {'Principal':30}  {'Method':30}  Result")
        print("─" * 100)

    for event in events:
        print(format_event(event, verbose))

def interactive_menu():
    """Interactive query menu."""
    while True:
        print("""
╔══════════════════════════════════════════════════════════════╗
║           Audit Log Query Tool                               ║
╠══════════════════════════════════════════════════════════════╣
║  [1]  Recent events (last 20)                                ║
║  [2]  Search by user/principal                               ║
║  [3]  Search by method (Create, Delete, etc.)                ║
║  [4]  Search by resource type                                ║
║  [5]  API Key operations                                     ║
║  [6]  Deletions only                                         ║
║  [7]  Creations only                                         ║
║  [8]  Authorization failures (DENY)                          ║
║  [9]  Authentication events                                  ║
║  [10] Cluster operations                                     ║
║  [11] Topic operations                                       ║
║  [12] Custom search                                          ║
║                                                              ║
║  [q]  Quit                                                   ║
╚══════════════════════════════════════════════════════════════╝
""")
        choice = input("Choose option: ").strip()

        if choice == 'q':
            print("Goodbye!")
            break
        elif choice == '1':
            events = query_recent(20)
            print_events(events)
        elif choice == '2':
            user = input("Enter user/principal to search: ").strip()
            events = query_recent(50, lambda e: user.lower() in str(e.get('principal', e.get('principal_email', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '3':
            method = input("Enter method to search (e.g., Create, Delete, Update): ").strip()
            events = query_recent(50, lambda e: method.lower() in str(e.get('methodName', e.get('method_name', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '4':
            rtype = input("Enter resource type (e.g., Topic, Cluster, Connector): ").strip()
            events = query_recent(50, lambda e: rtype.lower() in str(e.get('resourceType', e.get('resource_type', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '5':
            events = query_recent(50, lambda e: 'apikey' in str(e.get('methodName', e.get('resourceType', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '6':
            events = query_recent(50, lambda e: 'delete' in str(e.get('methodName', e.get('method_name', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '7':
            events = query_recent(50, lambda e: 'create' in str(e.get('methodName', e.get('method_name', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '8':
            events = query_recent(50, lambda e: e.get('granted') == False or e.get('resultStatus') == 'DENY' or e.get('authz_result') == 'DENY')
            print_events(events, verbose=True)
        elif choice == '9':
            events = query_recent(50, lambda e: 'authentication' in str(e.get('methodName', e.get('type', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '10':
            events = query_recent(50, lambda e: 'cluster' in str(e.get('resourceType', e.get('methodName', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '11':
            events = query_recent(50, lambda e: 'topic' in str(e.get('resourceType', e.get('resourceName', ''))).lower())
            print_events(events, verbose=True)
        elif choice == '12':
            field = input("Enter field name to search: ").strip()
            value = input("Enter value to search: ").strip()
            events = query_recent(50, lambda e: value.lower() in str(e.get(field, '')).lower())
            print_events(events, verbose=True)
        else:
            print("Invalid option")

        input("\nPress Enter to continue...")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--recent':
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            events = query_recent(limit)
            print_events(events)
        elif sys.argv[1] == '--user':
            user = sys.argv[2] if len(sys.argv) > 2 else ''
            events = query_recent(50, lambda e: user.lower() in str(e.get('principal', '')).lower())
            print_events(events, verbose=True)
        elif sys.argv[1] == '--type':
            mtype = sys.argv[2] if len(sys.argv) > 2 else ''
            events = query_recent(50, lambda e: mtype.lower() in str(e.get('methodName', '')).lower())
            print_events(events, verbose=True)
        else:
            print(__doc__)
    else:
        interactive_menu()
