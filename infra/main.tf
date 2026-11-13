locals {
  services = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "storage.googleapis.com",
    "aiplatform.googleapis.com",
  ])
  labels = { app = var.service_name, managed-by = "terraform" }
  secret_ids = {
    ADMIN_TOKEN           = "${var.service_name}-admin-token"
    WHATSAPP_VERIFY_TOKEN = "${var.service_name}-whatsapp-verify-token"
    WHATSAPP_APP_SECRET   = "${var.service_name}-whatsapp-app-secret"
    WHATSAPP_ACCESS_TOKEN = "${var.service_name}-whatsapp-access-token"
  }
  runtime_secrets = merge(
    { ADMIN_TOKEN = var.admin_secret_version },
    var.enable_whatsapp ? {
      WHATSAPP_VERIFY_TOKEN = var.whatsapp_secret_versions.verify_token
      WHATSAPP_APP_SECRET   = var.whatsapp_secret_versions.app_secret
      WHATSAPP_ACCESS_TOKEN = var.whatsapp_secret_versions.access_token
    } : {}
  )
  runtime_env = {
    ENVIRONMENT              = "production"
    GOOGLE_CLOUD_PROJECT     = var.project_id
    VERTEX_LOCATION          = "global"
    STORAGE_BACKEND          = "firestore"
    ENABLE_VERTEX_AI         = tostring(var.enable_vertex_ai)
    VERTEX_MODEL             = var.gemini_model
    WHATSAPP_PHONE_NUMBER_ID = var.enable_whatsapp ? var.whatsapp_phone_number_id : ""
    WHATSAPP_API_VERSION     = var.whatsapp_api_version
  }
}

resource "google_project_service" "api" {
  for_each           = local.services
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.service_name
  description   = "Nexo UNAL application container images"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-runtime"
  display_name = "Nexo UNAL Cloud Run runtime"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "builder" {
  account_id   = "${var.service_name}-builder"
  display_name = "Nexo UNAL image builder"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "runtime_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_vertex" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_firestore_database" "application" {
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = var.firestore_location
  type                        = "FIRESTORE_NATIVE"
  delete_protection_state     = "DELETE_PROTECTION_ENABLED"
  deletion_policy             = "ABANDON"
  app_engine_integration_mode = "DISABLED"
  depends_on                  = [google_project_service.api]
}

# Containers are Terraform-managed. Values never enter .tf files or Terraform state.
resource "google_secret_manager_secret" "application" {
  for_each  = local.secret_ids
  secret_id = each.value
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.runtime_secrets
  secret_id = google_secret_manager_secret.application[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "build_sources" {
  name                        = "${var.project_id}-${var.service_name}-build-sources"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  lifecycle_rule {
    condition { age = 7 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.api]
}

resource "google_storage_bucket_iam_member" "builder_sources" {
  bucket = google_storage_bucket.build_sources.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_artifact_registry_repository_iam_member" "builder_push" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_project_iam_member" "builder_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_cloud_run_v2_service" "application" {
  count               = var.container_image == null ? 0 : 1
  name                = var.service_name
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels
  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "300s"
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }
    containers {
      image = var.container_image
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = false
      }
      dynamic "env" {
        for_each = local.runtime_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.runtime_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.application[env.key].secret_id
              version = env.value
            }
          }
        }
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 20
        http_get { path = "/healthz" }
      }
      liveness_probe {
        timeout_seconds   = 3
        period_seconds    = 30
        failure_threshold = 3
        http_get { path = "/healthz" }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = !var.enable_whatsapp || length(var.whatsapp_phone_number_id) > 0
      error_message = "Set whatsapp_phone_number_id when enabling WhatsApp."
    }
  }
  depends_on = [
    google_project_service.api,
    google_secret_manager_secret_iam_member.runtime,
    google_project_iam_member.runtime_firestore,
    google_project_iam_member.runtime_vertex,
    google_firestore_database.application,
  ]
}

# Meta must reach the webhook without Google IAM. Administrative APIs verify ADMIN_TOKEN.
resource "google_cloud_run_v2_service_iam_member" "public_webhook" {
  count    = var.container_image == null ? 0 : 1
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.application[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_firestore_field" "expiry" {
  for_each   = toset(["metrics", "deliveries"])
  project    = var.project_id
  database   = google_firestore_database.application.name
  collection = each.key
  field      = "expires_at"
  # TTL activation is asynchronous and does not block serving the application.
  skip_wait = true
  ttl_config {}
}
