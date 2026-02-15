# Outputs for GCP deployment

output "cloud_run_service_name" {
  description = "Cloud Run service name"
  value       = google_cloud_run_v2_service.audit_forwarder.name
}

output "cloud_run_service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.audit_forwarder.uri
}

output "gcs_bucket_name" {
  description = "GCS bucket for audit logs"
  value       = google_storage_bucket.audit_logs.name
}

output "gcs_bucket_url" {
  description = "GCS bucket URL"
  value       = google_storage_bucket.audit_logs.url
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.audit_forwarder.repository_id}"
}

output "service_account_email" {
  description = "Service account email"
  value       = google_service_account.cloud_run.email
}

output "secret_id" {
  description = "Secret Manager secret ID"
  value       = google_secret_manager_secret.confluent_credentials.secret_id
}

output "kms_key_id" {
  description = "KMS crypto key ID"
  value       = google_kms_crypto_key.audit_logs.id
}
