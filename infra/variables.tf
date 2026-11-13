variable "project_id" {
  description = "Existing, billing-enabled Google Cloud project. Use a dedicated project."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Provide a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Cloud Run, Artifact Registry and build staging region."
  type        = string
  default     = "us-central1"
}

variable "firestore_location" {
  description = "Immutable location for a new Firestore database."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  type    = string
  default = "nexo-unal"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.service_name))
    error_message = "Use 3–20 lowercase characters, numbers or hyphens."
  }
}

variable "container_image" {
  description = "Immutable Artifact Registry image digest. Leave null for bootstrap only."
  type        = string
  default     = null
  validation {
    condition     = var.container_image == null ? true : can(regex("@sha256:[a-f0-9]{64}$", var.container_image))
    error_message = "Deploy an immutable image reference ending in @sha256:<64 hex characters>."
  }
}

variable "admin_secret_version" {
  description = "Numeric Secret Manager version; secret value is managed outside Terraform."
  type        = string
  default     = "1"
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.admin_secret_version))
    error_message = "Pin a numeric secret version."
  }
}

variable "enable_vertex_ai" {
  type    = bool
  default = false
}

variable "gemini_model" {
  description = "Vertex AI model ID available to the project in the selected region."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "enable_whatsapp" {
  description = "Mount WhatsApp credentials only after creating their Secret Manager versions."
  type        = bool
  default     = false
}

variable "whatsapp_phone_number_id" {
  description = "Meta phone number ID, not the phone number or access token."
  type        = string
  default     = ""
}

variable "whatsapp_api_version" {
  description = "Graph API version enabled for your Meta application."
  type        = string
  default     = "v25.0"
}

variable "whatsapp_secret_versions" {
  type = object({
    verify_token = string
    app_secret   = string
    access_token = string
  })
  default = {
    verify_token = "1"
    app_secret   = "1"
    access_token = "1"
  }
  validation {
    condition     = alltrue([for v in values(var.whatsapp_secret_versions) : can(regex("^[1-9][0-9]*$", v))])
    error_message = "Pin numeric versions for every WhatsApp secret."
  }
}

variable "max_instances" {
  description = "Scaling ceiling; not a spending cap."
  type        = number
  default     = 2
  validation {
    condition     = var.max_instances >= 1 && var.max_instances <= 5 && floor(var.max_instances) == var.max_instances
    error_message = "Set an integer from 1 to 5."
  }
}
