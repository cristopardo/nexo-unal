#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then
  echo "Usage: scripts/set-secret.sh PROJECT_ID SECRET_NAME" >&2
  exit 1
fi
# Read directly from terminal. Values are never shell arguments, files, or Terraform inputs.
IFS= read -r -s -p "Secret value: " SECRET_VALUE
printf '\n' >&2
if [[ ${#SECRET_VALUE} -lt 16 ]]; then
  unset SECRET_VALUE
  echo "Secret must contain at least 16 characters." >&2
  exit 1
fi
printf '%s' "$SECRET_VALUE" | gcloud secrets versions add "$2" --project="$1" --data-file=-
unset SECRET_VALUE
