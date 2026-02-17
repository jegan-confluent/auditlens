"""Tests for CRN Parser."""

import pytest
from src.transformer.crn_parser import CRNParser, CRNComponents


class TestCRNParser:
    """Test CRN parsing functionality."""

    def setup_method(self):
        self.parser = CRNParser()

    def test_parse_full_kafka_crn(self):
        """Test parsing a complete Kafka cluster CRN."""
        crn = "crn://confluent.cloud/organization=abc123/environment=env456/kafka=lkc-789xyz"
        result = self.parser.parse(crn)

        assert result.organization_id == "abc123"
        assert result.environment_id == "env456"
        assert result.cluster_type == "kafka"
        assert result.cluster_id == "lkc-789xyz"
        assert result.raw == crn

    def test_parse_kafka_topic_crn(self):
        """Test parsing a Kafka topic CRN."""
        crn = "crn://confluent.cloud/organization=abc123/environment=env456/kafka=lkc-789xyz/topic=audit-logs"
        result = self.parser.parse(crn)

        assert result.organization_id == "abc123"
        assert result.environment_id == "env456"
        assert result.cluster_type == "kafka"
        assert result.cluster_id == "lkc-789xyz"
        assert result.resource_type == "topic"
        assert result.resource_id == "audit-logs"

    def test_parse_schema_registry_crn(self):
        """Test parsing a Schema Registry CRN."""
        crn = "crn://confluent.cloud/organization=org1/environment=env1/schema-registry=lsrc-abc"
        result = self.parser.parse(crn)

        assert result.cluster_type == "schema-registry"
        assert result.cluster_id == "lsrc-abc"

    def test_parse_ksqldb_crn(self):
        """Test parsing a ksqlDB CRN."""
        crn = "crn://confluent.cloud/organization=org1/environment=env1/ksqldb=lksqlc-123"
        result = self.parser.parse(crn)

        assert result.cluster_type == "ksqldb"
        assert result.cluster_id == "lksqlc-123"

    def test_parse_flink_crn(self):
        """Test parsing a Flink CRN."""
        crn = "crn://confluent.cloud/organization=org1/environment=env1/flink=lfcp-456"
        result = self.parser.parse(crn)

        assert result.cluster_type == "flink"
        assert result.cluster_id == "lfcp-456"

    def test_parse_organization_only_crn(self):
        """Test parsing an organization-level CRN."""
        crn = "crn://confluent.cloud/organization=abc123"
        result = self.parser.parse(crn)

        assert result.organization_id == "abc123"
        assert result.environment_id is None
        assert result.cluster_type is None

    def test_parse_none_crn(self):
        """Test parsing None CRN returns empty components."""
        result = self.parser.parse(None)

        assert result.raw == ""  # Empty string, not None
        assert result.is_valid is False
        assert result.organization_id is None
        assert result.environment_id is None

    def test_parse_empty_string_crn(self):
        """Test parsing empty string CRN."""
        result = self.parser.parse("")

        assert result.raw == ""
        assert result.is_valid is False
        assert result.organization_id is None

    def test_parse_invalid_crn_prefix(self):
        """Test parsing CRN with invalid prefix."""
        crn = "invalid://confluent.cloud/organization=abc123"
        result = self.parser.parse(crn)

        # Should still store raw but not parse components
        assert result.raw == crn
        assert result.is_valid is False
        assert result.organization_id is None

    def test_parse_group_crn(self):
        """Test parsing a consumer group CRN."""
        crn = "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123/group=my-group"
        result = self.parser.parse(crn)

        assert result.resource_type == "group"
        assert result.resource_id == "my-group"

    def test_extract_cluster_id(self):
        """Test extracting cluster ID."""
        crn = "crn://confluent.cloud/organization=org1/environment=env1/kafka=lkc-123"
        cluster_id = self.parser.extract_cluster_id(crn)

        assert cluster_id == "lkc-123"

    def test_extract_organization_id(self):
        """Test extracting organization ID."""
        crn = "crn://confluent.cloud/organization=abc123/environment=env1/kafka=lkc-123"
        org_id = self.parser.extract_organization_id(crn)

        assert org_id == "abc123"

    def test_crn_components_to_dict(self):
        """Test CRNComponents to_dict method."""
        components = CRNComponents(
            raw="crn://confluent.cloud/organization=org1",
            is_valid=True,
            organization_id="org1",
            environment_id="env1",
            cluster_type="kafka",
            cluster_id="lkc-123"
        )
        result = components.to_dict()

        # to_dict uses crn_ prefix for keys
        assert result["crn_organization_id"] == "org1"
        assert result["crn_environment_id"] == "env1"
        assert result["crn_cluster_type"] == "kafka"
        assert result["crn_cluster_id"] == "lkc-123"
