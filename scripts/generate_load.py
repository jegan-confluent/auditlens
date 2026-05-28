#!/usr/bin/env python3
"""Generate test load for Audit Forwarder testing."""

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from confluent_kafka import Producer


def delivery_report(err, msg):
    """Delivery callback for produced messages."""
    if err is not None:
        print(f"Message delivery failed: {err}")


def generate_authentication_event(org_id: str, env_id: str, cluster_id: str) -> dict:
    """Generate a Kafka authentication event."""
    principals = [
        "User:sa-service-account-1",
        "User:sa-service-account-2",
        "User:admin@example.com",
        "User:developer@example.com",
        "User:unknown-user",
    ]
    statuses = ["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS", "UNAUTHENTICATED"]

    return {
        "id": str(uuid.uuid4()),
        "specversion": "1.0",
        "source": f"crn://confluent.cloud/organization={org_id}/environment={env_id}/kafka={cluster_id}",
        "type": "io.confluent.kafka.server/authentication",
        "time": datetime.now(timezone.utc).isoformat() + "Z",
        "subject": f"crn://confluent.cloud/organization={org_id}/environment={env_id}/kafka={cluster_id}",
        "datacontenttype": "application/json",
        "data": {
            "authenticationInfo": {
                "principal": random.choice(principals)
            },
            "methodName": "kafka.Authentication",
            "serviceName": f"crn://confluent.cloud/organization={org_id}/environment={env_id}/kafka={cluster_id}",
            "result": {
                "status": random.choice(statuses)
            },
            "requestMetadata": {
                "clientAddress": f"192.168.1.{random.randint(1, 254)}"
            }
        }
    }


def generate_authorization_event(org_id: str, env_id: str, cluster_id: str) -> dict:
    """Generate a Kafka authorization event."""
    principals = [
        "User:sa-service-account-1",
        "User:sa-service-account-2",
        "User:developer@example.com",
    ]
    topics = ["orders", "payments", "users", "audit-logs", "restricted-data"]
    operations = ["Read", "Write", "Describe", "Create", "Delete"]
    statuses = ["SUCCESS", "SUCCESS", "SUCCESS", "PERMISSION_DENIED"]

    status = random.choice(statuses)

    return {
        "id": str(uuid.uuid4()),
        "specversion": "1.0",
        "source": f"crn://confluent.cloud/organization={org_id}/environment={env_id}/kafka={cluster_id}",
        "type": "io.confluent.kafka.server/authorization",
        "time": datetime.now(timezone.utc).isoformat() + "Z",
        "data": {
            "authenticationInfo": {
                "principal": random.choice(principals)
            },
            "authorizationInfo": {
                "resourceType": "Topic",
                "resourceName": random.choice(topics),
                "operation": random.choice(operations),
                "patternType": "LITERAL",
                "granted": status == "SUCCESS"
            },
            "methodName": f"kafka.{random.choice(['Produce', 'Fetch', 'Metadata'])}",
            "result": {
                "status": status,
                "message": "User not authorized" if status == "PERMISSION_DENIED" else None
            }
        }
    }


def generate_request_event(org_id: str) -> dict:
    """Generate a cloud request event."""
    methods = [
        "CreateEnvironment",
        "CreateKafkaCluster",
        "UpdateServiceAccount",
        "CreateApiKey",
        "DeleteApiKey",
        "UpdateRBAC",
    ]
    principals = [
        "User:admin@example.com",
        "User:platform-admin@example.com",
    ]

    return {
        "id": str(uuid.uuid4()),
        "specversion": "1.0",
        "source": f"crn://confluent.cloud/organization={org_id}",
        "type": "io.confluent.cloud/request",
        "time": datetime.now(timezone.utc).isoformat() + "Z",
        "data": {
            "authenticationInfo": {
                "principal": random.choice(principals)
            },
            "methodName": random.choice(methods),
            "serviceName": "organization",
            "result": {
                "status": "SUCCESS"
            }
        }
    }


def generate_access_transparency_event(org_id: str) -> dict:
    """Generate an access transparency event (rare)."""
    return {
        "id": str(uuid.uuid4()),
        "specversion": "1.0",
        "source": f"crn://confluent.cloud/organization={org_id}",
        "type": "io.confluent.cloud/access-transparency",
        "time": datetime.now(timezone.utc).isoformat() + "Z",
        "data": {
            "authenticationInfo": {
                "principal": "support@example.com"
            },
            "methodName": "SupportAccess",
            "serviceName": "support",
            "result": {
                "status": "SUCCESS"
            },
            "accessTransparency": {
                "reason": "Customer-initiated support ticket",
                "caseNumber": f"CS-2025-{random.randint(10000, 99999)}",
                "accessedBy": "engineer@example.com"
            }
        }
    }


def generate_event() -> dict:
    """Generate a random audit event."""
    org_id = f"org-{random.choice(['abc123', 'def456', 'ghi789'])}"
    env_id = f"env-{random.choice(['prod', 'staging', 'dev'])}"
    cluster_id = f"lkc-{random.randint(100000, 999999)}"

    # Weight event types (authentication most common, access transparency rare)
    event_type = random.choices(
        ["authentication", "authorization", "request", "access_transparency"],
        weights=[50, 40, 9, 1],
        k=1
    )[0]

    if event_type == "authentication":
        return generate_authentication_event(org_id, env_id, cluster_id)
    elif event_type == "authorization":
        return generate_authorization_event(org_id, env_id, cluster_id)
    elif event_type == "request":
        return generate_request_event(org_id)
    else:
        return generate_access_transparency_event(org_id)


def main():
    """Main entry point."""
    bootstrap = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    topic = os.getenv("TOPIC", "confluent-audit-log-events")
    num_events = int(os.getenv("NUM_EVENTS", "1000"))
    batch_size = int(os.getenv("BATCH_SIZE", "100"))

    print(f"Generating {num_events} events to {topic} @ {bootstrap}")

    producer_config = {
        "bootstrap.servers": bootstrap,
        "client.id": "load-generator",
        "acks": "all",
        "compression.type": "snappy",
        "batch.size": 16384,
        "linger.ms": 10,
    }

    producer = Producer(producer_config)

    start_time = datetime.now()

    for i in range(num_events):
        event = generate_event()

        producer.produce(
            topic,
            key=event.get("data", {}).get("authenticationInfo", {}).get("principal", "unknown").encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report
        )

        if (i + 1) % batch_size == 0:
            producer.flush()
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"Produced {i + 1}/{num_events} events ({rate:.1f} events/sec)")

    producer.flush()

    elapsed = (datetime.now() - start_time).total_seconds()
    rate = num_events / elapsed if elapsed > 0 else 0

    print(f"\nCompleted! Produced {num_events} events in {elapsed:.2f}s ({rate:.1f} events/sec)")


if __name__ == "__main__":
    main()
