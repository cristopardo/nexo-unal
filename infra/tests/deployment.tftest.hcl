mock_provider "google" {}

variables {
  # Isolate mock tests from the operator's ignored deployment variable files.
  project_id               = "nexo-unal-validation"
  container_image          = null
  enable_vertex_ai         = false
  enable_whatsapp          = false
  whatsapp_phone_number_id = ""
  admin_secret_version     = "1"
  max_instances            = 2
}

run "bootstrap_does_not_expose_an_unconfigured_service" {
  command = plan

  assert {
    condition     = length(google_cloud_run_v2_service.application) == 0
    error_message = "Bootstrap must not create a service without an immutable application image."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.runtime) == 1 && contains(keys(google_secret_manager_secret_iam_member.runtime), "ADMIN_TOKEN")
    error_message = "The runtime must only receive access to the admin secret until WhatsApp is enabled."
  }
  assert {
    condition     = length(google_project_iam_member.runtime_vertex) == 0
    error_message = "Vertex privileges must be absent until the feature is enabled."
  }
}

run "service_has_bounded_scale_and_pinned_secrets" {
  command = plan
  variables {
    container_image = "us-central1-docker.pkg.dev/nexo-unal-validation/nexo-unal/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition     = google_cloud_run_v2_service.application[0].template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.application[0].template[0].scaling[0].max_instance_count == 2
    error_message = "The first deployment must scale to zero and be limited to two instances."
  }
  assert {
    condition     = alltrue([for env in google_cloud_run_v2_service.application[0].template[0].containers[0].env : env.name != "ADMIN_TOKEN" || env.value_source[0].secret_key_ref[0].version == "1"])
    error_message = "Admin access must use a fixed Secret Manager version."
  }
}

run "whatsapp_requires_a_phone_registration" {
  command = plan
  variables {
    container_image = "us-central1-docker.pkg.dev/nexo-unal-validation/nexo-unal/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    enable_whatsapp = true
  }
  expect_failures = [google_cloud_run_v2_service.application[0]]
}
