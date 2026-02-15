# Outputs for Confluent Cloud resources

output "service_account_id" {
  description = "Service account ID"
  value       = confluent_service_account.audit_forwarder.id
}

output "service_account_name" {
  description = "Service account display name"
  value       = confluent_service_account.audit_forwarder.display_name
}

# Audit Cluster Credentials (Source)
output "audit_api_key" {
  description = "API key for audit log cluster"
  value       = confluent_api_key.audit_consumer.id
  sensitive   = true
}

output "audit_api_secret" {
  description = "API secret for audit log cluster"
  value       = confluent_api_key.audit_consumer.secret
  sensitive   = true
}

output "audit_bootstrap_servers" {
  description = "Bootstrap servers for audit log cluster"
  value       = data.confluent_kafka_cluster.audit.bootstrap_endpoint
}

# Destination Cluster Credentials
output "dest_api_key" {
  description = "API key for destination cluster"
  value       = confluent_api_key.dest_producer.id
  sensitive   = true
}

output "dest_api_secret" {
  description = "API secret for destination cluster"
  value       = confluent_api_key.dest_producer.secret
  sensitive   = true
}

output "dest_bootstrap_servers" {
  description = "Bootstrap servers for destination cluster"
  value       = data.confluent_kafka_cluster.dest.bootstrap_endpoint
}

# Schema Registry Credentials
output "schema_registry_api_key" {
  description = "API key for Schema Registry"
  value       = confluent_api_key.schema_registry.id
  sensitive   = true
}

output "schema_registry_api_secret" {
  description = "API secret for Schema Registry"
  value       = confluent_api_key.schema_registry.secret
  sensitive   = true
}

output "schema_registry_url" {
  description = "Schema Registry REST endpoint"
  value       = data.confluent_schema_registry_cluster.main.rest_endpoint
}

# Topics
output "dest_topic_name" {
  description = "Destination topic name"
  value       = confluent_kafka_topic.audit_logs_processed.topic_name
}

output "dlq_topic_name" {
  description = "DLQ topic name"
  value       = confluent_kafka_topic.dlq.topic_name
}

# Environment variables for the forwarder (copy to .env or secrets manager)
output "forwarder_env_vars" {
  description = "Environment variables for the audit forwarder"
  sensitive   = true
  value = <<-EOT
    # Audit Log Cluster (Source)
    AUDIT_BOOTSTRAP=${data.confluent_kafka_cluster.audit.bootstrap_endpoint}
    AUDIT_API_KEY=${confluent_api_key.audit_consumer.id}
    AUDIT_API_SECRET=${confluent_api_key.audit_consumer.secret}
    AUDIT_TOPICS=confluent-audit-log-events

    # Destination Cluster
    DEST_BOOTSTRAP=${data.confluent_kafka_cluster.dest.bootstrap_endpoint}
    DEST_API_KEY=${confluent_api_key.dest_producer.id}
    DEST_API_SECRET=${confluent_api_key.dest_producer.secret}
    DEST_TOPIC=${confluent_kafka_topic.audit_logs_processed.topic_name}

    # Schema Registry
    SCHEMA_REGISTRY_URL=${data.confluent_schema_registry_cluster.main.rest_endpoint}
    SCHEMA_REGISTRY_KEY=${confluent_api_key.schema_registry.id}
    SCHEMA_REGISTRY_SECRET=${confluent_api_key.schema_registry.secret}

    # DLQ
    DLQ_TOPIC=${confluent_kafka_topic.dlq.topic_name}
  EOT
}

# =============================================================================
# Tableflow Outputs
# =============================================================================

output "tableflow_enabled" {
  description = "Whether Tableflow is enabled"
  value       = var.tableflow_enabled
}

output "tableflow_s3_bucket" {
  description = "S3 bucket for Tableflow Iceberg tables"
  value       = var.tableflow_enabled ? var.tableflow_s3_bucket : null
}

output "glue_database_name" {
  description = "AWS Glue database name (based on cluster ID)"
  value       = var.tableflow_enabled && var.glue_enabled ? data.confluent_kafka_cluster.dest.id : null
}

# =============================================================================
# Flink Outputs
# =============================================================================

output "flink_enabled" {
  description = "Whether Flink is enabled"
  value       = var.flink_enabled
}

output "flink_compute_pool_id" {
  description = "Flink compute pool ID"
  value       = var.flink_enabled ? confluent_flink_compute_pool.audit_processing[0].id : null
}

output "flink_api_key" {
  description = "Flink API key"
  value       = var.flink_enabled ? confluent_api_key.flink[0].id : null
  sensitive   = true
}

output "flink_api_secret" {
  description = "Flink API secret"
  value       = var.flink_enabled ? confluent_api_key.flink[0].secret : null
  sensitive   = true
}

output "flink_rest_endpoint" {
  description = "Flink REST endpoint for submitting SQL statements"
  value       = var.flink_enabled ? "https://flink.${var.flink_region}.aws.confluent.cloud" : null
}

output "alert_topics" {
  description = "Alert topics created for Flink processing"
  value = var.flink_enabled ? {
    auth_failures       = confluent_kafka_topic.auth_failure_alerts[0].topic_name
    access_transparency = confluent_kafka_topic.access_transparency_alerts[0].topic_name
    hourly_stats        = confluent_kafka_topic.hourly_stats[0].topic_name
  } : null
}
