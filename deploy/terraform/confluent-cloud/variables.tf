# Variables for Confluent Cloud resources

# Confluent Cloud API
variable "confluent_cloud_api_key" {
  description = "Confluent Cloud API Key (with OrganizationAdmin or EnvironmentAdmin role)"
  type        = string
  sensitive   = true
}

variable "confluent_cloud_api_secret" {
  description = "Confluent Cloud API Secret"
  type        = string
  sensitive   = true
}

# Environment
variable "environment_id" {
  description = "Confluent Cloud Environment ID"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, production)"
  type        = string
  default     = "dev"
}

# Audit Log Cluster (Source)
variable "audit_cluster_id" {
  description = "Kafka cluster ID for audit logs"
  type        = string
}

variable "audit_cluster_admin_key" {
  description = "Admin API key for audit log cluster (for ACL management)"
  type        = string
  sensitive   = true
}

variable "audit_cluster_admin_secret" {
  description = "Admin API secret for audit log cluster"
  type        = string
  sensitive   = true
}

# Destination Cluster
variable "dest_cluster_id" {
  description = "Kafka cluster ID for destination"
  type        = string
}

variable "dest_cluster_admin_key" {
  description = "Admin API key for destination cluster"
  type        = string
  sensitive   = true
}

variable "dest_cluster_admin_secret" {
  description = "Admin API secret for destination cluster"
  type        = string
  sensitive   = true
}

# Topics
variable "dest_topic" {
  description = "Destination topic name"
  type        = string
  default     = "audit-logs-processed"
}

variable "dlq_topic" {
  description = "Dead letter queue topic name"
  type        = string
  default     = "audit-logs-dlq"
}

variable "topic_partitions" {
  description = "Number of partitions for destination topic"
  type        = number
  default     = 6
}

variable "topic_retention_ms" {
  description = "Retention period for destination topic (ms)"
  type        = number
  default     = 604800000 # 7 days
}

variable "dlq_retention_ms" {
  description = "Retention period for DLQ topic (ms)"
  type        = number
  default     = 2592000000 # 30 days
}

# =============================================================================
# Tableflow Configuration
# =============================================================================

variable "tableflow_enabled" {
  description = "Enable Tableflow for automatic Iceberg table materialization"
  type        = bool
  default     = false
}

variable "tableflow_s3_bucket" {
  description = "S3 bucket for Tableflow Iceberg tables"
  type        = string
  default     = ""
}

variable "tableflow_s3_region" {
  description = "AWS region for Tableflow S3 bucket"
  type        = string
  default     = "us-west-2"
}

variable "confluent_aws_account_id" {
  description = "Confluent's AWS account ID for cross-account access"
  type        = string
  default     = "831762378940"  # Confluent's production AWS account
}

variable "glue_enabled" {
  description = "Enable AWS Glue catalog integration"
  type        = bool
  default     = false
}

variable "glue_catalog_id" {
  description = "AWS Glue Catalog ID (typically your AWS account ID)"
  type        = string
  default     = ""
}

# =============================================================================
# Flink Configuration
# =============================================================================

variable "flink_enabled" {
  description = "Enable Flink SQL processing"
  type        = bool
  default     = false
}

variable "flink_region" {
  description = "AWS region for Flink compute pool"
  type        = string
  default     = "us-west-2"
}

variable "flink_max_cfu" {
  description = "Maximum Confluent Flink Units for compute pool"
  type        = number
  default     = 10
}

variable "alert_topic_retention_ms" {
  description = "Retention period for alert topics (ms)"
  type        = number
  default     = 604800000 # 7 days
}

variable "stats_topic_retention_ms" {
  description = "Retention period for stats topics (ms)"
  type        = number
  default     = 2592000000 # 30 days
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "audit-forwarder"
}
