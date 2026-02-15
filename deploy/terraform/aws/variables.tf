################################################################################
# Variables
################################################################################

# General
variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "auditlens"
}

# VPC
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b"]
}

# ECS - Forwarder
variable "forwarder_cpu" {
  description = "CPU units for forwarder task (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "forwarder_memory" {
  description = "Memory (MB) for forwarder task"
  type        = number
  default     = 1024
}

variable "forwarder_desired_count" {
  description = "Desired number of forwarder tasks"
  type        = number
  default     = 1
}

variable "forwarder_image_tag" {
  description = "Docker image tag for forwarder"
  type        = string
  default     = "v2.2.0"
}

# ECS - Dashboard
variable "dashboard_cpu" {
  description = "CPU units for dashboard task"
  type        = number
  default     = 256
}

variable "dashboard_memory" {
  description = "Memory (MB) for dashboard task"
  type        = number
  default     = 512
}

variable "dashboard_desired_count" {
  description = "Desired number of dashboard tasks"
  type        = number
  default     = 2
}

variable "dashboard_image_tag" {
  description = "Docker image tag for dashboard"
  type        = string
  default     = "v10.19"
}

# Kafka Configuration
variable "kafka_source_bootstrap" {
  description = "Source Kafka bootstrap servers (audit log cluster)"
  type        = string
  sensitive   = true
}

variable "kafka_source_api_key" {
  description = "Source Kafka API key"
  type        = string
  sensitive   = true
}

variable "kafka_source_api_secret" {
  description = "Source Kafka API secret"
  type        = string
  sensitive   = true
}

variable "kafka_dest_bootstrap" {
  description = "Destination Kafka bootstrap servers"
  type        = string
  sensitive   = true
}

variable "kafka_dest_api_key" {
  description = "Destination Kafka API key"
  type        = string
  sensitive   = true
}

variable "kafka_dest_api_secret" {
  description = "Destination Kafka API secret"
  type        = string
  sensitive   = true
}

# Forwarder Configuration
variable "audit_topic" {
  description = "Source audit log topic name"
  type        = string
  default     = "confluent-audit-log-events"
}

variable "consumer_group_id" {
  description = "Kafka consumer group ID"
  type        = string
  default     = "audit-forwarder-fargate"
}

variable "enable_multi_topic_routing" {
  description = "Enable routing to criticality-based topics"
  type        = bool
  default     = true
}

variable "drop_low_events" {
  description = "Drop LOW criticality events to save storage"
  type        = bool
  default     = true
}

variable "enable_dlq" {
  description = "Enable Dead Letter Queue for failed events"
  type        = bool
  default     = true
}

# Monitoring
variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "enable_container_insights" {
  description = "Enable ECS Container Insights"
  type        = bool
  default     = true
}

# Cost Optimization
variable "use_fargate_spot" {
  description = "Use Fargate Spot for forwarder (70% cheaper, can be interrupted)"
  type        = bool
  default     = false
}
