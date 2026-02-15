# =============================================================================
# Tableflow Configuration for Confluent Cloud
# =============================================================================
# Enables automatic Iceberg table materialization with AWS Glue integration

# -----------------------------------------------------------------------------
# Provider Integration for S3 Access
# -----------------------------------------------------------------------------

resource "confluent_provider_integration" "tableflow_s3" {
  count = var.tableflow_enabled ? 1 : 0

  display_name = "${var.project_name}-tableflow-s3"
  environment {
    id = data.confluent_environment.audit.id
  }

  aws {
    customer_role_arn = aws_iam_role.tableflow_s3[0].arn
  }
}

# -----------------------------------------------------------------------------
# IAM Role for Tableflow S3 Access
# -----------------------------------------------------------------------------

resource "aws_iam_role" "tableflow_s3" {
  count = var.tableflow_enabled ? 1 : 0

  name = "${var.project_name}-tableflow-s3-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.confluent_aws_account_id}:root"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = confluent_provider_integration.tableflow_s3[0].aws[0].external_id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "tableflow_s3" {
  count = var.tableflow_enabled ? 1 : 0

  name = "${var.project_name}-tableflow-s3-policy"
  role = aws_iam_role.tableflow_s3[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${var.tableflow_s3_bucket}",
          "arn:aws:s3:::${var.tableflow_s3_bucket}/*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Tableflow-Enabled Topics
# -----------------------------------------------------------------------------

# Enable Tableflow on processed audit logs topic
resource "confluent_tableflow_topic" "audit_logs_processed" {
  count = var.tableflow_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name = confluent_kafka_topic.audit_logs_processed.topic_name

  # Use custom S3 storage
  storage {
    type = "CUSTOM"
    custom {
      provider_integration {
        id = confluent_provider_integration.tableflow_s3[0].id
      }
      bucket        = var.tableflow_s3_bucket
      bucket_region = var.tableflow_s3_region
    }
  }

  environment {
    id = data.confluent_environment.audit.id
  }

  depends_on = [
    confluent_provider_integration.tableflow_s3,
    aws_iam_role_policy.tableflow_s3
  ]
}

# Enable Tableflow on hourly stats topic
resource "confluent_tableflow_topic" "audit_hourly_stats" {
  count = var.tableflow_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name = "audit-hourly-stats"

  storage {
    type = "CUSTOM"
    custom {
      provider_integration {
        id = confluent_provider_integration.tableflow_s3[0].id
      }
      bucket        = var.tableflow_s3_bucket
      bucket_region = var.tableflow_s3_region
    }
  }

  environment {
    id = data.confluent_environment.audit.id
  }

  depends_on = [
    confluent_provider_integration.tableflow_s3,
    aws_iam_role_policy.tableflow_s3
  ]
}

# Enable Tableflow on security events (for quick security queries)
resource "confluent_tableflow_topic" "auth_failure_alerts" {
  count = var.tableflow_enabled ? 1 : 0

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  topic_name = "audit-auth-failure-alerts"

  storage {
    type = "CUSTOM"
    custom {
      provider_integration {
        id = confluent_provider_integration.tableflow_s3[0].id
      }
      bucket        = var.tableflow_s3_bucket
      bucket_region = var.tableflow_s3_region
    }
  }

  environment {
    id = data.confluent_environment.audit.id
  }

  depends_on = [
    confluent_provider_integration.tableflow_s3,
    aws_iam_role_policy.tableflow_s3
  ]
}

# -----------------------------------------------------------------------------
# AWS Glue Catalog Integration
# -----------------------------------------------------------------------------

resource "confluent_catalog_integration" "aws_glue" {
  count = var.tableflow_enabled && var.glue_enabled ? 1 : 0

  display_name = "${var.project_name}-glue-catalog"

  kafka_cluster {
    id = data.confluent_kafka_cluster.dest.id
  }

  environment {
    id = data.confluent_environment.audit.id
  }

  aws_glue {
    provider_integration {
      id = confluent_provider_integration.glue_catalog[0].id
    }
    catalog_id = var.glue_catalog_id
    region     = var.tableflow_s3_region
  }
}

# Provider Integration for Glue Access
resource "confluent_provider_integration" "glue_catalog" {
  count = var.tableflow_enabled && var.glue_enabled ? 1 : 0

  display_name = "${var.project_name}-glue-catalog"
  environment {
    id = data.confluent_environment.audit.id
  }

  aws {
    customer_role_arn = aws_iam_role.tableflow_glue[0].arn
  }
}

# IAM Role for Glue Catalog Access
resource "aws_iam_role" "tableflow_glue" {
  count = var.tableflow_enabled && var.glue_enabled ? 1 : 0

  name = "${var.project_name}-tableflow-glue-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.confluent_aws_account_id}:root"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = confluent_provider_integration.glue_catalog[0].aws[0].external_id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "tableflow_glue" {
  count = var.tableflow_enabled && var.glue_enabled ? 1 : 0

  name = "${var.project_name}-tableflow-glue-policy"
  role = aws_iam_role.tableflow_glue[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:CreateDatabase",
          "glue:UpdateDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:BatchCreatePartition",
          "glue:BatchDeletePartition",
          "glue:BatchUpdatePartition"
        ]
        Resource = [
          "arn:aws:glue:${var.tableflow_s3_region}:${var.glue_catalog_id}:catalog",
          "arn:aws:glue:${var.tableflow_s3_region}:${var.glue_catalog_id}:database/*",
          "arn:aws:glue:${var.tableflow_s3_region}:${var.glue_catalog_id}:table/*/*"
        ]
      }
    ]
  })
}
