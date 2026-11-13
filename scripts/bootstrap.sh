#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFVARS="${1:-$ROOT_DIR/infra/terraform.tfvars}"
if [[ ! -f "$TFVARS" ]]; then
  echo "Create infra/terraform.tfvars from the example and select a dedicated project." >&2
  exit 1
fi
# ADC is intentionally configured by the operator, never by repository code.
if [[ -z "${GOOGLE_OAUTH_ACCESS_TOKEN:-}" ]]; then
  gcloud auth application-default print-access-token >/dev/null
fi
terraform -chdir="$ROOT_DIR/infra" init
terraform -chdir="$ROOT_DIR/infra" plan -var-file="$TFVARS" -out=bootstrap.tfplan
terraform -chdir="$ROOT_DIR/infra" apply bootstrap.tfplan
