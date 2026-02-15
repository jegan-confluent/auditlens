"""
Confluent Resource Name (CRN) parser.

CRN Format:
    crn://confluent.cloud/[organization=<id>/][environment=<id>/][<type>=<id>]

Examples:
    crn://confluent.cloud/organization=abc123
    crn://confluent.cloud/organization=abc123/environment=env-xyz
    crn://confluent.cloud/kafka=lkc-abc123
    crn://confluent.cloud/kafka=lkc-abc123/topic=my-topic
    crn://confluent.cloud/organization=abc/environment=env-1/cloud-cluster=lkc-123/kafka=lkc-123
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum


class ResourceType(str, Enum):
    """Known Confluent resource types."""
    ORGANIZATION = "organization"
    ENVIRONMENT = "environment"
    KAFKA = "kafka"
    CLOUD_CLUSTER = "cloud-cluster"
    SCHEMA_REGISTRY = "schema-registry"
    KSQLDB = "ksqldb"
    FLINK = "flink"
    CONNECT = "connect"
    CONNECTOR = "connector"
    TOPIC = "topic"
    GROUP = "group"
    TRANSACTIONAL_ID = "transactional-id"
    CLUSTER_LINK = "cluster-link"
    SUBJECT = "subject"
    SERVICE_ACCOUNT = "service-account"
    USER = "user"
    API_KEY = "api-key"
    IDENTITY_POOL = "identity-pool"
    IDENTITY_PROVIDER = "identity-provider"
    NETWORK = "network"
    PEERING = "peering"
    PRIVATE_LINK = "private-link"
    COMPUTE_POOL = "compute-pool"
    STATEMENT = "statement"
    UNKNOWN = "unknown"


@dataclass
class CRNComponents:
    """Parsed CRN components."""
    raw: str
    is_valid: bool = False
    organization_id: Optional[str] = None
    environment_id: Optional[str] = None
    cluster_type: Optional[str] = None  # kafka, schema-registry, ksqldb, flink
    cluster_id: Optional[str] = None
    resource_type: Optional[str] = None  # topic, group, subject, etc.
    resource_id: Optional[str] = None
    all_components: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Convert to dictionary for flattening."""
        return {
            "crn_raw": self.raw,
            "crn_organization_id": self.organization_id,
            "crn_environment_id": self.environment_id,
            "crn_cluster_type": self.cluster_type,
            "crn_cluster_id": self.cluster_id,
            "crn_resource_type": self.resource_type,
            "crn_resource_id": self.resource_id,
        }


class CRNParser:
    """
    Parser for Confluent Resource Names (CRNs).

    Usage:
        parser = CRNParser()
        components = parser.parse("crn://confluent.cloud/kafka=lkc-abc123/topic=my-topic")
        print(components.cluster_id)  # "lkc-abc123"
        print(components.resource_type)  # "topic"
        print(components.resource_id)  # "my-topic"
    """

    CRN_PREFIX = "crn://confluent.cloud/"
    CLUSTER_TYPES = {"kafka", "schema-registry", "ksqldb", "flink", "connect"}
    RESOURCE_TYPES = {
        "topic", "group", "transactional-id", "cluster-link", "subject",
        "connector", "statement", "compute-pool", "service-account",
        "user", "api-key", "identity-pool", "identity-provider",
        "network", "peering", "private-link"
    }

    def parse(self, crn: Optional[str]) -> CRNComponents:
        """Parse a CRN string into its components."""
        if not crn:
            return CRNComponents(raw="", is_valid=False)

        if not crn.startswith(self.CRN_PREFIX):
            return CRNComponents(raw=crn, is_valid=False)

        # Extract path after prefix
        path = crn[len(self.CRN_PREFIX):]
        if not path:
            return CRNComponents(raw=crn, is_valid=True)

        # Parse key=value pairs
        components: Dict[str, str] = {}
        for segment in path.split("/"):
            if "=" in segment:
                key, value = segment.split("=", 1)
                components[key] = value

        # Build result
        result = CRNComponents(
            raw=crn,
            is_valid=True,
            all_components=components,
        )

        # Extract organization
        result.organization_id = components.get("organization")

        # Extract environment
        result.environment_id = components.get("environment")

        # Extract cluster info
        for cluster_type in self.CLUSTER_TYPES:
            if cluster_type in components:
                result.cluster_type = cluster_type
                result.cluster_id = components[cluster_type]
                break

        # Also check cloud-cluster
        if "cloud-cluster" in components:
            result.cluster_id = components["cloud-cluster"]
            # Try to determine type from other fields
            if not result.cluster_type:
                cluster_id = components["cloud-cluster"]
                if cluster_id.startswith("lkc-"):
                    result.cluster_type = "kafka"
                elif cluster_id.startswith("lsrc-"):
                    result.cluster_type = "schema-registry"
                elif cluster_id.startswith("lksqlc-"):
                    result.cluster_type = "ksqldb"

        # Extract leaf resource
        for resource_type in self.RESOURCE_TYPES:
            if resource_type in components:
                result.resource_type = resource_type
                result.resource_id = components[resource_type]
                break

        return result

    def parse_source(self, source: Optional[str]) -> CRNComponents:
        """Parse a source CRN (typically points to service/cluster)."""
        return self.parse(source)

    def parse_subject(self, subject: Optional[str]) -> CRNComponents:
        """Parse a subject CRN (typically points to affected resource)."""
        return self.parse(subject)

    def extract_cluster_id(self, crn: Optional[str]) -> Optional[str]:
        """Extract just the cluster ID from a CRN."""
        components = self.parse(crn)
        return components.cluster_id

    def extract_environment_id(self, crn: Optional[str]) -> Optional[str]:
        """Extract just the environment ID from a CRN."""
        components = self.parse(crn)
        return components.environment_id

    def extract_organization_id(self, crn: Optional[str]) -> Optional[str]:
        """Extract just the organization ID from a CRN."""
        components = self.parse(crn)
        return components.organization_id

    @staticmethod
    def extract_kafka_cluster_from_resource_name(resource_name: Optional[str]) -> Optional[str]:
        """
        Extract Kafka cluster ID from a resource name.

        Resource names may contain kafka cluster IDs in various formats:
        - crn://confluent.cloud/kafka=lkc-abc123/topic=foo
        - kafka=lkc-abc123
        """
        if not resource_name:
            return None

        # Try to find kafka= pattern
        match = re.search(r'kafka=([a-zA-Z0-9-]+)', resource_name)
        if match:
            return match.group(1)

        # Try to find lkc- pattern directly
        match = re.search(r'(lkc-[a-zA-Z0-9]+)', resource_name)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def build_crn(
        organization_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        cluster_type: Optional[str] = None,
        cluster_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> str:
        """Build a CRN from components."""
        parts = ["crn://confluent.cloud"]

        if organization_id:
            parts.append(f"organization={organization_id}")
        if environment_id:
            parts.append(f"environment={environment_id}")
        if cluster_type and cluster_id:
            parts.append(f"{cluster_type}={cluster_id}")
        if resource_type and resource_id:
            parts.append(f"{resource_type}={resource_id}")

        return "/".join(parts)
