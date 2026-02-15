# =============================================================================
# Flink SQL Configuration for Confluent Cloud
# =============================================================================
# Deploys Flink SQL statements for audit log processing

# -----------------------------------------------------------------------------
# Flink Compute Pool
# -----------------------------------------------------------------------------

resource "confluent_flink_compute_pool" "audit_processing" {
  count = var.flink_enabled ? 1 : 0

  display_name = "${var.project_name}-flink-pool"
  cloud        = "AWS"
  region       = var.flink_region

  max_cfu = var.flink_max_cfu

  environment {
    id = data.confluent_environment.audit.id
  }
}

# -----------------------------------------------------------------------------
# Service Account for Flink
# -----------------------------------------------------------------------------

resource "confluent_service_account" "flink" {
  count = var.flink_enabled ? 1 : 0

  display_name = "${var.project_name}-flink-sa"
  description  = "Service account for Flink SQL processing"
}

# Role Binding: Flink Admin
resource "confluent_role_binding" "flink_admin" {
  count = var.flink_enabled ? 1 : 0

  principal   = "User:${confluent_service_account.flink[0].id}"
  role_name   = "FlinkAdmin"
  crn_pattern = data.confluent_environment.audit.resource_name
}

# Role Binding: Kafka access for Flink
resource "confluent_role_binding" "flink_kafka_access" {
  count = var.flink_enabled ? 1 : 0

  principal   = "User:${confluent_service_account.flink[0].id}"
  role_name   = "CloudClusterAdmin"
  crn_pattern = data.confluent_kafka_cluster.dest.rbac_crn
}

# API Key for Flink
resource "confluent_api_key" "flink" {
  count = var.flink_enabled ? 1 : 0

  display_name = "${var.project_name}-flink-api-key"
  description  = "API key for Flink SQL statements"

  owner {
    id          = confluent_service_account.flink[0].id
    api_version = confluent_service_account.flink[0].api_version
    kind        = confluent_service_account.flink[0].kind
  }

  managed_resource {
    id          = confluent_flink_compute_pool.audit_processing[0].id
    api_version = confluent_flink_compute_pool.audit_processing[0].api_version
    kind        = confluent_flink_compute_pool.audit_processing[0].kind

    environment {
      id = data.confluent_environment.audit.id
    }
  }
}

# -----------------------------------------------------------------------------
# Flink SQL Statements
# -----------------------------------------------------------------------------

# Note: Flink SQL statements are typically deployed via CI/CD or manually
# This creates the output topics that Flink will write to

# Topic: Auth Failure Alerts
resource "confluent_kafka_topic" "auth_failure_alerts" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name       = "audit-auth-failure-alerts"
  partitions_count = 3

  config = {
    "retention.ms"     = tostring(var.alert_topic_retention_ms)
    "cleanup.policy"   = "delete"
    "compression.type" = "snappy"
  }

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# Topic: Access Transparency Alerts
resource "confluent_kafka_topic" "access_transparency_alerts" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name       = "audit-access-transparency-alerts"
  partitions_count = 3

  config = {
    "retention.ms"     = tostring(var.alert_topic_retention_ms)
    "cleanup.policy"   = "delete"
    "compression.type" = "snappy"
  }

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# Topic: Hourly Stats
resource "confluent_kafka_topic" "hourly_stats" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name       = "audit-hourly-stats"
  partitions_count = 6

  config = {
    "retention.ms"     = tostring(var.stats_topic_retention_ms)
    "cleanup.policy"   = "compact,delete"
    "compression.type" = "snappy"
  }

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}

# ACLs for Flink to read from audit topic
resource "confluent_kafka_acl" "flink_read_audit" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.audit.id
  }

  resource_type = "TOPIC"
  resource_name = "confluent-audit-log-events"
  pattern_type  = "LITERAL"
  principal     = "User:${confluent_service_account.flink[0].id}"
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.audit.rest_endpoint

  credentials {
    key    = var.audit_cluster_admin_key
    secret = var.audit_cluster_admin_secret
  }
}

# ACLs for Flink consumer group
resource "confluent_kafka_acl" "flink_consumer_group" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.audit.id
  }

  resource_type = "GROUP"
  resource_name = "flink-"
  pattern_type  = "PREFIXED"
  principal     = "User:${confluent_service_account.flink[0].id}"
  host          = "*"
  operation     = "READ"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.audit.rest_endpoint

  credentials {
    key    = var.audit_cluster_admin_key
    secret = var.audit_cluster_admin_secret
  }
}

# ACLs for Flink to write to destination topics
resource "confluent_kafka_acl" "flink_write_dest" {
  count = var.flink_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  resource_type = "TOPIC"
  resource_name = "audit-"
  pattern_type  = "PREFIXED"
  principal     = "User:${confluent_service_account.flink[0].id}"
  host          = "*"
  operation     = "WRITE"
  permission    = "ALLOW"

  rest_endpoint = data.confluent_kafka_cluster.dest.rest_endpoint

  credentials {
    key    = var.dest_cluster_admin_key
    secret = var.dest_cluster_admin_secret
  }
}
