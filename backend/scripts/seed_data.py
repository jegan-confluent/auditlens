from datetime import datetime, timedelta, timezone

from backend.app.db.database import SessionLocal, init_db
from backend.app.services.event_service import create_event


SEED_EVENTS = [
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=35),
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "sa-pvqqxy",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=error-lcc-p76qzm",
        "resourceType": "Topic",
        "summary": "sa-pvqqxy created topic 'error-lcc-p76qzm'",
        "resultStatus": "Success",
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.10",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=30),
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "u-75rw9o",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=jegan-testing",
        "resourceType": "Topic",
        "summary": "u-75rw9o created topic 'jegan-testing'",
        "resultStatus": "Success",
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.11",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=25),
        "methodName": "kafka.DeleteTopics",
        "action": "DeleteTopics",
        "user": "u-75rw9o",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=old-topic",
        "resourceType": "Topic",
        "summary": "u-75rw9o deleted topic 'old-topic'",
        "resultStatus": "Success",
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.11",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=20),
        "methodName": "kafka.CreateTopics",
        "action": "CreateTopics",
        "user": "sa-pvqqxy",
        "resourceName": "crn://confluent.cloud/organization=o/environment=e/cloud-cluster=lkc-demo/topic=error-lcc-p76qzm",
        "resourceType": "Topic",
        "summary": "sa-pvqqxy failed to create topic 'error-lcc-p76qzm'",
        "resultStatus": "Failure",
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.10",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=15),
        "methodName": "kafka.Authorize",
        "action": "Authorize",
        "user": "u-no-access",
        "resourceName": "Topic: payments",
        "resourceType": "Topic",
        "summary": "u-no-access failed authorization for topic 'payments'",
        "resultStatus": "Failure",
        "granted": False,
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.12",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=10),
        "methodName": "kafka.Authorize",
        "action": "Authorize",
        "user": "u-denied",
        "resourceName": "Topic: payroll",
        "resourceType": "Topic",
        "summary": "u-denied was denied access to topic 'payroll'",
        "resultStatus": "Denied",
        "granted": False,
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.13",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=8),
        "methodName": "kafka.Authenticate",
        "action": "Authenticate",
        "user": "sa-routine",
        "resourceName": "Cluster: lkc-demo",
        "resourceType": "Cluster",
        "summary": "sa-routine authenticated with Kafka",
        "resultStatus": "Success",
        "cluster_id": "lkc-demo",
        "source_ip": "10.10.0.14",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=5),
        "methodName": "iam.CreateApiKey",
        "action": "CreateApiKey",
        "user": "u-admin",
        "resourceName": "API Key: ABC123",
        "resourceType": "API Key",
        "summary": "u-admin created API key 'ABC123'",
        "resultStatus": "Success",
        "source_ip": "10.10.0.15",
    },
    {
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=3),
        "methodName": "TableflowGetTable",
        "action": "TableflowGetTable",
        "user": "u-reader",
        "resourceName": "Tableflow table: orders",
        "resourceType": "Tableflow",
        "summary": "u-reader read Tableflow table 'orders'",
        "resultStatus": "Success",
        "source_ip": "10.10.0.16",
    },
]


def main() -> None:
    init_db()
    with SessionLocal() as db:
        for payload in SEED_EVENTS:
            create_event(db, payload)
    print(f"Seeded {len(SEED_EVENTS)} audit events")


if __name__ == "__main__":
    main()
