terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

# ADC by default; GOOGLE_OAUTH_ACCESS_TOKEN supports an operator's short-lived token.
provider "google" {}

variable "project_id" {
  description = "Globally unique ID for a new dedicated project."
  type        = string
  default     = "nexo-unal-2026"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Provide a valid Google Cloud project ID."
  }
}

variable "billing_account" {
  description = "Existing open billing account ID; keep it in ignored local terraform.tfvars."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$", var.billing_account))
    error_message = "Use the billing account ID in XXXXXX-XXXXXX-XXXXXX format."
  }
}

variable "organization_id" {
  description = "Optional organization ID. Mutually exclusive with folder_id."
  type        = string
  default     = null
}

variable "folder_id" {
  description = "Optional parent folder ID. Mutually exclusive with organization_id."
  type        = string
  default     = null
}

resource "google_project" "nexo" {
  project_id          = var.project_id
  name                = "Nexo UNAL"
  billing_account     = var.billing_account
  org_id              = var.organization_id
  folder_id           = var.folder_id
  auto_create_network = false
  deletion_policy     = "PREVENT"
  labels = {
    app        = "nexo-unal"
    managed-by = "terraform"
  }
  lifecycle {
    precondition {
      condition     = var.organization_id == null || var.folder_id == null
      error_message = "Choose either an organization or a folder, not both."
    }
  }
}

output "project_id" {
  value = google_project.nexo.project_id
}

output "project_number" {
  value = google_project.nexo.number
}
