#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${AZURE_RESOURCE_GROUP:?set AZURE_RESOURCE_GROUP}"
: "${AZURE_FUNCTION_APP_NAME:?set AZURE_FUNCTION_APP_NAME}"

"$ROOT_DIR/scripts/azure/build_function_zip.sh"

az functionapp deployment source config-zip \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_FUNCTION_APP_NAME" \
  --src "$ROOT_DIR/cloud-functions/.deployment/reality-authenticator-functions.zip" \
  --output none

printf 'Deployed %s\n' "$AZURE_FUNCTION_APP_NAME"
