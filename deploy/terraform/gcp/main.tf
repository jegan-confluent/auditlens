# Terraform configuration for GCP deployment
# Deploys Audit Forwarder to Cloud Run with GCS sink

terraform {
  required_version = ">= 1.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    confluent = {
      source  = "confluentinc/confluent"
      version = "~> 1.60"
    }
  }

  # Uncomment to use remote state
  # backend "gcs" {
  #   bucket = "your-terraform-state-bucket"
  #   prefix = "audit-forwarder/terraform"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

provider "confluent" {
  cloud_api_key    = var.confluent_cloud_api_key
  cloud_api_secret = var.confluent_cloud_api_secret
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudkms.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ])

  service            = each.key
  disable_on_destroy = false
}

# GCS Bucket for audit logs
resource "google_storage_bucket" "audit_logs" {
  name          = "${var.project_name}-${var.environment}-audit-logs-${var.project_id}"
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.audit_logs.id
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = var.audit_log_retention_days
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    project     = var.project_name
    environment = var.environment
  }

  depends_on = [google_project_service.apis]
}

# KMS Key Ring
resource "google_kms_key_ring" "audit_logs" {
  name     = "${var.project_name}-keyring"
  location = var.region

  depends_on = [google_project_service.apis]
}

# KMS Crypto Key
resource "google_kms_crypto_key" "audit_logs" {
  name            = "${var.project_name}-key"
  key_ring        = google_kms_key_ring.audit_logs.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = true
  }
}

# Secret Manager - Confluent Credentials
resource "google_secret_manager_secret" "confluent_credentials" {
  secret_id = "${var.project_name}-confluent-credentials"

  replication {
    auto {}
  }

  labels = {
    project     = var.project_name
    environment = var.environment
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "confluent_credentials" {
  secret = google_secret_manager_secret.confluent_credentials.id

  secret_data = jsonencode({
    audit_api_key       = var.audit_api_key
    audit_api_secret    = var.audit_api_secret
    dest_api_key        = var.dest_api_key
    dest_api_secret     = var.dest_api_secret
    sr_api_key          = var.schema_registry_key
    sr_api_secret       = var.schema_registry_secret
  })
}

# Artifact Registry
resource "google_artifact_registry_repository" "audit_forwarder" {
  location      = var.region
  repository_id = var.project_name
  format        = "DOCKER"

  labels = {
    project     = var.project_name
    environment = var.environment
  }

  depends_on = [google_project_service.apis]
}

# Service Account for Cloud Run
resource "google_service_account" "cloud_run" {
  account_id   = "${var.project_name}-run"
  display_name = "Audit Forwarder Cloud Run Service Account"
}

# IAM - GCS Access
resource "google_storage_bucket_iam_member" "audit_logs_writer" {
  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_storage_bucket_iam_member" "audit_logs_viewer" {
  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

# IAM - Secret Manager Access
resource "google_secret_manager_secret_iam_member" "secret_accessor" {
  secret_id = google_secret_manager_secret.confluent_credentials.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# IAM - KMS Access
resource "google_kms_crypto_key_iam_member" "encrypter" {
  crypto_key_id = google_kms_crypto_key.audit_logs.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Cloud Run Service
resource "google_cloud_run_v2_service" "audit_forwarder" {
  name     = var.project_name
  location = var.region

  template {
    service_account = google_service_account.cloud_run.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.audit_forwarder.repository_id}/${var.project_name}:${var.image_tag}"

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      ports {
        container_port = 8000
      }

      # Environment variables
      env {
        name  = "AUDIT_BOOTSTRAP"
        value = var.audit_bootstrap
      }
      env {
        name  = "AUDIT_TOPICS"
        value = var.audit_topics
      }
      env {
        name  = "DEST_BOOTSTRAP"
        value = var.dest_bootstrap
      }
      env {
        name  = "DEST_TOPIC"
        value = var.dest_topic
      }
      env {
        name  = "SCHEMA_REGISTRY_URL"
        value = var.schema_registry_url
      }
      env {
        name  = "S3_ENABLED"
        value = "false"
      }
      env {
        name  = "GCS_ENABLED"
        value = "true"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.audit_logs.name
      }
      env {
        name  = "GCS_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCS_PREFIX"
        value = "confluent-audit-logs/"
      }
      env {
        name  = "GCS_FORMAT"
        value = "parquet"
      }
      env {
        name  = "DLQ_ENABLED"
        value = "true"
      }
      env {
        name  = "DLQ_TOPIC"
        value = var.dlq_topic
      }
      env {
        name  = "METRICS_PORT"
        value = "8000"
      }
      env {
        name  = "HEALTH_PORT"
        value = "8001"
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }
      env {
        name  = "SECRETS_BACKEND"
        value = "gcp"
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      # Secrets from Secret Manager
      env {
        name = "AUDIT_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.confluent_credentials.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8001
        }
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/live"
          port = 8001
        }
        initial_delay_seconds = 30
        timeout_seconds       = 3
        period_seconds        = 30
        failure_threshold     = 3
      }
    }

    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = var.vpc_network
        subnetwork = var.vpc_subnet
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  labels = {
    project     = var.project_name
    environment = var.environment
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.confluent_credentials
  ]
}

# Cloud Run IAM - Allow unauthenticated for health checks (internal only)
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.audit_forwarder.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Cloud Monitoring Alert Policy
resource "google_monitoring_alert_policy" "high_error_rate" {
  display_name = "${var.project_name}-high-error-rate"
  combiner     = "OR"

  conditions {
    display_name = "High Error Rate"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.project_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class!=\"2xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 10

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = var.notification_channels

  alert_strategy {
    auto_close = "604800s"
  }
}

# Cloud Monitoring Dashboard
resource "google_monitoring_dashboard" "audit_forwarder" {
  dashboard_json = jsonencode({
    displayName = "Audit Forwarder Dashboard"
    gridLayout = {
      columns = 2
      widgets = [
        {
          title = "Request Count"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.project_name}\" AND metric.type=\"run.googleapis.com/request_count\""
                }
              }
            }]
          }
        },
        {
          title = "Instance Count"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.project_name}\" AND metric.type=\"run.googleapis.com/container/instance_count\""
                }
              }
            }]
          }
        },
        {
          title = "CPU Utilization"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.project_name}\" AND metric.type=\"run.googleapis.com/container/cpu/utilizations\""
                }
              }
            }]
          }
        },
        {
          title = "Memory Utilization"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.project_name}\" AND metric.type=\"run.googleapis.com/container/memory/utilizations\""
                }
              }
            }]
          }
        }
      ]
    }
  })
}
