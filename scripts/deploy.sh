#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFVARS="${1:-$ROOT_DIR/infra/terraform.tfvars}"
if [[ ! -f "$TFVARS" ]]; then
  echo "Missing Terraform variables file. Run bootstrap first." >&2
  exit 1
fi
cd "$ROOT_DIR"
# Read approved project configuration from Terraform state, never gcloud's ambient default.
REPOSITORY="$(terraform -chdir=infra output -raw image_repository)"
BUILD_SA="$(terraform -chdir=infra output -raw builder_service_account)"
SOURCE_BUCKET="$(terraform -chdir=infra output -raw build_source_bucket)"
PROJECT_ID="${BUILD_SA#projects/}"
PROJECT_ID="${PROJECT_ID%%/*}"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Commit the source before building so the image has a reproducible revision." >&2
  exit 1
fi
REVISION="$(git rev-parse --short=12 HEAD)"
IMAGE_TAG="$REPOSITORY/app:$REVISION"
gcloud builds submit "$ROOT_DIR" \
  --project="$PROJECT_ID" \
  --config="$ROOT_DIR/cloudbuild.yaml" \
  --service-account="$BUILD_SA" \
  --gcs-source-staging-dir="gs://$SOURCE_BUCKET/source" \
  --substitutions="_IMAGE=$IMAGE_TAG"
DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG" --project="$PROJECT_ID" --format='value(image_summary.digest)')"
if [[ ! "$DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "Could not resolve immutable image digest." >&2
  exit 1
fi
IMAGE_REF="$REPOSITORY/app@$DIGEST"
printf 'container_image = "%s"\n' "$IMAGE_REF" > "$ROOT_DIR/infra/deployment.auto.tfvars"
terraform -chdir=infra plan -var-file="$TFVARS" -var="container_image=$IMAGE_REF" -out=deploy.tfplan
terraform -chdir=infra apply deploy.tfplan
SERVICE_URL="$(terraform -chdir=infra output -raw service_url)"
curl --fail --silent --show-error "$SERVICE_URL/health"
printf '\nDeployment URL: %s\nImage: %s\n' "$SERVICE_URL" "$IMAGE_REF"
printf 'Image recorded in ignored infra/deployment.auto.tfvars.\n'
