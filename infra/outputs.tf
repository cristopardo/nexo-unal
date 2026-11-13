output "service_url" {
  value = try(google_cloud_run_v2_service.application[0].uri, null)
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "builder_service_account" {
  value = google_service_account.builder.name
}

output "build_source_bucket" {
  value = google_storage_bucket.build_sources.name
}

output "secret_names" {
  value = { for key, secret in google_secret_manager_secret.application : key => secret.secret_id }
}
