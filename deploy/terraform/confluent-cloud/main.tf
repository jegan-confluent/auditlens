# Terraform configuration for Confluent Cloud resources
# Creates the necessary topics, service accounts, and API keys

terraform {
  required_version = ">= 1.0"

  required_providers {
    confluent = {
      source  = "confluentinc/confluent"
      version = "~> 1.60"
    }
  }
}

provider "confluent" {
  cloud_api_key    = var.confluent_cloud_api_key
  cloud_api_secret = var.confluent_cloud_api_secret
}

# Data sources for existing resources
data "confluent_organization" "main" {}

data "confluent_environment" "audit" {
  id = var.environment_id
}

# Get the audit log cluster (read-only)
data "confluent_kafka_cluster" "audit" {
  id = var.audit_cluster_id

  environment {
    id = data.confluent_environment.audit.id
  }
}

# Destination cluster for processed logs
data "confluent_kafka_cluster" "dest" {
  id = var.dest_cluster_id

  environment {
    id = data.confluent_environment.audit.id
  }
}

# Schema Registry
data "confluent_schema_registry_cluster" "main" {
  environment {
    id = data.confluent_environment.audit.id
  }
}

# Service Account for Audit Forwarder
resource "confluent_service_account" "audit_forwarder" {
  display_name = "audit-forwarder-${var.environment}"
  description  = "Service account for Audit Log Forwarder"
}

# ============================================
# Audit Log Cluster (Source) - Read Access
# ============================================

# API Key for reading from audit log cluster
resource "confluent_api_key" "audit_consumer" {
  display_name = "audit-forwarder-consumer-key"
  description  = "API key for consuming audit logs"

  owner {
    id          = confluent_service_account.audit_forwarder.id
    api_version = confluent_service_account.audit_forwarder.api_version
    kind        = confluent_service_account.audit_forwarder.kind
  }

  managed_resource {
    id          = data.confluent_kafka_cluster.audit.id
    api_version = data.confluent_kafka_cluster.audit.api_version
    kind        = data.confluent_kafka_cluster.audit.kind

    environment {
      id = data.confluent_environment.audit.id
    }
  }
}

# ACL: Read from audit log topics
resource "confluent_kafka_acl" "audit_read_topic" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.audit.id
  }

  resource_type = "TOPIC"
  resource_name = "confluent-audit-log-events"
  pattern_type  = "LITERAL"
  principal     = "User:${confluent_service_account.audit_forwarder.id}"
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.audit.rest_endpoint

  credentials {
    key    = var.audit_cluster_admin_key
    secret = var.audit_cluster_admin_secret
  }
}

# ACL: Consumer group for audit forwarder
resource "confluent_kafka_acl" "audit_consumer_group" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.audit.id
  }

  resource_type = "GROUP"
  resource_name = "audit-forwarder-"
  pattern_type  = "PREFIXED"
  principal     = "User:${confluent_service_account.audit_forwarder.id}"
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.audit.rest_endpoint

  credentials {
    key    = var.audit_cluster_admin_key
    secret = var.audit_cluster_admin_secret
  }
}

# ============================================
# Destination Cluster - Write Access
# ============================================

# API Key for writing to destination cluster
resource "confluent_api_key" "dest_producer" {
  display_name = "audit-forwarder-producer-key"
  description  = "API key for producing processed audit logs"

  owner {
    id          = confluent_service_account.audit_forwarder.id
    api_version = confluent_service_account.audit_forwarder.api_version
    kind        = confluent_service_account.audit_forwarder.kind
  }

  managed_resource {
    id          = data.confluent_kafka_cluster.dest.id
    api_version = data.confluent_kafka_cluster.dest.api_version
    kind        = data.confluent_kafka_cluster.dest.kind

    environment {
      id = data.confluent_environment.audit.id
    }
  }
}

# Topic: Processed audit logs
resource "confluent_kafka_topic" "audit_logs_processed" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name       = var.dest_topic
  partitions_count = var.topic_partitions

  config = {
    "retention.ms"    = tostring(var.topic_retention_ms)
    "cleanup.policy"  = "delete"
    "compression.type" = "snappy"
  }

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# Topic: Dead Letter Queue
resource "confluent_kafka_topic" "dlq" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name       = var.dlq_topic
  partitions_count = 3

  config = {
    "retention.ms"    = tostring(var.dlq_retention_ms)
    "cleanup.policy"  = "delete"
    "compression.type" = "snappy"
  }

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# ACL: Write to processed topic
resource "confluent_kafka_acl" "dest_write_topic" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  resource_type = "TOPIC"
  resource_name = confluent_kafka_topic.audit_logs_processed.topic_name
  pattern_type  = "LITERAL"
  principal     = "User:${confluent_service_account.audit_forwarder.id}"
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# ACL: Write to DLQ topic
resource "confluent_kafka_acl" "dlq_write_topic" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  resource_type = "TOPIC"
  resource_name = confluent_kafka_topic.dlq.topic_name
  pattern_type  = "LITERAL"
  principal     = "User:${confluent_service_account.audit_forwarder.id}"
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# ACL: Describe topics (for metadata)
resource "confluent_kafka_acl" "dest_describe_topic" {
  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  resource_type = "TOPIC"
  resource_name = "*"
  pattern_type  = "LITERAL"
  principal     = "User:${confluent_service_account.audit_forwarder.id}"
  host          = "*"
  operation     = "DESCRIBE"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# ============================================
# Schema Registry Access
# ============================================

# API Key for Schema Registry
resource "confluent_api_key" "schema_registry" {
  display_name = "audit-forwarder-sr-key"
  description  = "API key for Schema Registry"

  owner {
    id          = confluent_service_account.audit_forwarder.id
    api_version = confluent_service_account.audit_forwarder.api_version
    kind        = confluent_service_account.audit_forwarder.kind
  }

  managed_resource {
    id          = data.confluent_schema_registry_cluster.main.id
    api_version = data.confluent_schema_registry_cluster.main.api_version
    kind        = data.confluent_schema_registry_cluster.main.kind

    environment {
      id = data.confluent_environment.audit.id
    }
  }
}
