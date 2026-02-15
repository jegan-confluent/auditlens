# ============================================================================
# Confluent Cloud Audit Log Analyzer - Main Terraform Configuration
# ============================================================================
# This deploys everything needed to analyze Confluent Cloud audit logs:
# 1. Flink Compute Pool
# 2. Flink SQL statements for schema flattening and aggregations
# 3. Service accounts and API keys
# ============================================================================

terraform {
  required_version = ">= 1.3.0"

  required_providers {
    confluent = {
      source  = "confluentinc/confluent"
      version = ">= 2.0.0"
    }
  }
}

# ============================================================================
# Variables
# ============================================================================

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

variable "environment_id" {
  description = "Confluent Cloud Environment ID (e.g., env-abc123)"
  type        = string
}

variable "audit_log_cluster_id" {
  description = "Audit Log Kafka Cluster ID (e.g., lkc-abc123)"
  type        = string
}

variable "flink_region" {
  description = "Region for Flink compute pool"
  type        = string
  default     = "us-east-1"
}

variable "flink_cloud" {
  description = "Cloud provider for Flink (AWS, GCP, AZURE)"
  type        = string
  default     = "AWS"
}

variable "flink_max_cfu" {
  description = "Maximum CFUs for Flink compute pool (5-50)"
  type        = number
  default     = 10
}

variable "project_name" {
  description = "Name prefix for resources"
  type        = string
  default     = "audit-analyzer"
}

# ============================================================================
# Provider Configuration
# ============================================================================

provider "confluent" {
  cloud_api_key    = var.confluent_cloud_api_key
  cloud_api_secret = var.confluent_cloud_api_secret
}

# ============================================================================
# Data Sources
# ============================================================================

data "confluent_environment" "main" {
  id = var.environment_id
}

data "confluent_kafka_cluster" "audit_log" {
  id = var.audit_log_cluster_id
  environment {
    id = data.confluent_environment.main.id
  }
}

# ============================================================================
# Service Account for Flink
# ============================================================================

resource "confluent_service_account" "flink_sa" {
  display_name = "${var.project_name}-flink-sa"
  description  = "Service account for Flink audit log processing"
}

# Grant Flink access to the audit log cluster
resource "confluent_role_binding" "flink_cluster_admin" {
  principal   = "User:${confluent_service_account.flink_sa.id}"
  role_name   = "CloudClusterAdmin"
  crn_pattern = data.confluent_kafka_cluster.audit_log.rbac_crn
}

resource "confluent_role_binding" "flink_developer" {
  principal   = "User:${confluent_service_account.flink_sa.id}"
  role_name   = "FlinkDeveloper"
  crn_pattern = data.confluent_environment.main.resource_name
}

# ============================================================================
# Flink Compute Pool
# ============================================================================

resource "confluent_flink_compute_pool" "audit_analyzer" {
  display_name = "${var.project_name}-compute-pool"
  cloud        = var.flink_cloud
  region       = var.flink_region
  max_cfu      = var.flink_max_cfu

  environment {
    id = data.confluent_environment.main.id
  }

  lifecycle {
    prevent_destroy = false
  }
}

# ============================================================================
# API Keys for Flink
# ============================================================================

resource "confluent_api_key" "flink_api_key" {
  display_name = "${var.project_name}-flink-api-key"
  description  = "API key for Flink compute pool"

  owner {
    id          = confluent_service_account.flink_sa.id
    api_version = confluent_service_account.flink_sa.api_version
    kind        = confluent_service_account.flink_sa.kind
  }

  managed_resource {
    id          = confluent_flink_compute_pool.audit_analyzer.id
    api_version = confluent_flink_compute_pool.audit_analyzer.api_version
    kind        = confluent_flink_compute_pool.audit_analyzer.kind

    environment {
      id = data.confluent_environment.main.id
    }
  }
}

# ============================================================================
# Flink SQL Statements
# ============================================================================

# Read SQL files
locals {
  sql_source_table    = file("${path.module}/../../flink-sql/01_audit_events_source.sql")
  sql_flattened_table = file("${path.module}/../../flink-sql/02_audit_events_flattened.sql")
  sql_aggregations    = file("${path.module}/../../flink-sql/03_aggregation_tables.sql")
}

# Deploy source table statement
resource "confluent_flink_statement" "source_table" {
  organization {
    id = data.confluent_environment.main.id
  }

  environment {
    id = data.confluent_environment.main.id
  }

  compute_pool {
    id = confluent_flink_compute_pool.audit_analyzer.id
  }

  principal {
    id = confluent_service_account.flink_sa.id
  }

  statement     = local.sql_source_table
  statement_name = "${var.project_name}-source-table"

  properties = {
    "sql.current-catalog"  = data.confluent_environment.main.display_name
    "sql.current-database" = data.confluent_kafka_cluster.audit_log.display_name
  }

  credentials {
    key    = confluent_api_key.flink_api_key.id
    secret = confluent_api_key.flink_api_key.secret
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "flink_compute_pool_id" {
  description = "Flink Compute Pool ID"
  value       = confluent_flink_compute_pool.audit_analyzer.id
}

output "flink_service_account_id" {
  description = "Flink Service Account ID"
  value       = confluent_service_account.flink_sa.id
}

output "flink_api_key_id" {
  description = "Flink API Key ID"
  value       = confluent_api_key.flink_api_key.id
}

output "environment_id" {
  description = "Environment ID"
  value       = data.confluent_environment.main.id
}

output "next_steps" {
  description = "Next steps after deployment"
  value       = <<-EOT

    ========================================
    Audit Log Analyzer Deployed Successfully!
    ========================================

    Flink Compute Pool: ${confluent_flink_compute_pool.audit_analyzer.id}

    Next Steps:
    1. Go to Confluent Cloud Console > Flink
    2. Select your compute pool: ${confluent_flink_compute_pool.audit_analyzer.display_name}
    3. Run the SQL statements from flink-sql/ directory in order:
       - 01_audit_events_source.sql
       - 02_audit_events_flattened.sql
       - 03_aggregation_tables.sql

    Or use the CLI:

    confluent flink statement create --sql "$(cat flink-sql/02_audit_events_flattened.sql)" \
      --compute-pool ${confluent_flink_compute_pool.audit_analyzer.id} \
      --environment ${data.confluent_environment.main.id}

    Query the flattened data:

    SELECT * FROM audit_events_flattened WHERE is_deletion = TRUE;
    SELECT * FROM audit_security_events ORDER BY window_start DESC LIMIT 10;
    SELECT * FROM audit_deletions ORDER BY event_time DESC LIMIT 20;

  EOT
}
