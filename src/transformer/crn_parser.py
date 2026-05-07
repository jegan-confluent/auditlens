"""Compatibility wrapper for the shared CRN parser."""

from src.product.resource_intelligence import CRNComponents, parse_crn


class CRNParser:
    def parse(self, crn):
        return parse_crn(crn)

    def parse_source(self, source):
        return parse_crn(source)

    def parse_subject(self, subject):
        return parse_crn(subject)

    def extract_cluster_id(self, crn):
        return parse_crn(crn).cluster_id

    def extract_environment_id(self, crn):
        return parse_crn(crn).environment_id

    def extract_organization_id(self, crn):
        return parse_crn(crn).organization_id

    @staticmethod
    def extract_kafka_cluster_from_resource_name(resource_name):
        if not resource_name:
            return None
        components = parse_crn(resource_name)
        if components.cluster_id:
            return components.cluster_id
        if "kafka=" in resource_name:
            return resource_name.split("kafka=", 1)[1].split("/", 1)[0]
        if "lkc-" in resource_name:
            return "lkc-" + resource_name.split("lkc-", 1)[1].split("/", 1)[0]
        return None

    @staticmethod
    def build_crn(
        organization_id=None,
        environment_id=None,
        cluster_type=None,
        cluster_id=None,
        resource_type=None,
        resource_id=None,
    ):
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
