# Variables for GCP deployment

# Project
variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "audit-forwarder"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, production)"
  type        = string
  default     = "dev"
}

# GCP
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

# VPC (for Private Google Access)
variable "vpc_network" {
  description = "VPC network name for Cloud Run"
  type        = string
  default     = "default"
}

variable "vpc_subnet" {
  description = "VPC subnet name for Cloud Run"
  type        = string
  default     = "default"
}

# Cloud Run
variable "cpu" {
  description = "CPU allocation for Cloud Run"
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory allocation for Cloud Run"
  type        = string
  default     = "1Gi"
}

variable "min_instances" {
  description = "Minimum number of instances"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum number of instances"
  type        = number
  default     = 10
}

variable "image_tag" {
  description = "Docker image tag"
  type        = string
  default     = "latest"
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated access to Cloud Run service"
  type        = bool
  default     = false
}

# Confluent Cloud
variable "confluent_cloud_api_key" {
  description = "Confluent Cloud API Key"
  type        = string
  sensitive   = true
}

variable "confluent_cloud_api_secret" {
  description = "Confluent Cloud API Secret"
  type        = string
  sensitive   = true
}

variable "audit_bootstrap" {
  description = "Bootstrap servers for audit log cluster"
  type        = string
}

variable "audit_topics" {
  description = "Comma-separated list of audit log topics"
  type        = string
  default     = "confluent-audit-log-events"
}

variable "audit_api_key" {
  description = "API key for audit log cluster"
  type        = string
  sensitive   = true
}

variable "audit_api_secret" {
  description = "API secret for audit log cluster"
  type        = string
  sensitive   = true
}

variable "dest_bootstrap" {
  description = "Bootstrap servers for destination cluster"
  type        = string
}

variable "dest_topic" {
  description = "Destination topic for processed events"
  type        = string
  default     = "audit-logs-processed"
}

variable "dest_api_key" {
  description = "API key for destination cluster"
  type        = string
  sensitive   = true
}

variable "dest_api_secret" {
  description = "API secret for destination cluster"
  type        = string
  sensitive   = true
}

variable "dlq_topic" {
  description = "Dead letter queue topic"
  type        = string
  default     = "audit-logs-dlq"
}

# Schema Registry
variable "schema_registry_url" {
  description = "Schema Registry URL"
  type        = string
}

variable "schema_registry_key" {
  description = "Schema Registry API key"
  type        = string
  sensitive   = true
}

variable "schema_registry_secret" {
  description = "Schema Registry API secret"
  type        = string
  sensitive   = true
}

# GCS
variable "audit_log_retention_days" {
  description = "Number of days to retain audit logs in GCS"
  type        = number
  default     = 365
}

# Logging
variable "log_level" {
  description = "Log level (DEBUG, INFO, WARNING, ERROR)"
  type        = string
  default     = "INFO"
}

# Alerting
variable "notification_channels" {
  description = "List of notification channel IDs for alerts"
  type        = list(string)
  default     = []
}
