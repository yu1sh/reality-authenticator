#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_RESOURCE_GROUP:?set AZURE_RESOURCE_GROUP}"
: "${AZURE_LOCATION:?set AZURE_LOCATION}"
: "${AZURE_STORAGE_ACCOUNT_NAME:?set AZURE_STORAGE_ACCOUNT_NAME}"
: "${AZURE_FUNCTION_APP_NAME:?set AZURE_FUNCTION_APP_NAME}"
: "${ADMIN_API_KEY:?set ADMIN_API_KEY}"
: "${AZURE_KEY_VAULT_NAME:?set AZURE_KEY_VAULT_NAME}"
: "${AZURE_IOT_HUB_NAME:?set AZURE_IOT_HUB_NAME}"

EVIDENCE_CONTAINER="${AZURE_BLOB_CONTAINER_EVIDENCE:-reality-evidence}"
PROOFS_CONTAINER="${AZURE_BLOB_CONTAINER_PROOFS:-reality-proofs}"
SESSIONS_TABLE="${AZURE_TABLE_SESSIONS:-RealitySessions}"
EVIDENCE_TABLE="${AZURE_TABLE_EVIDENCE:-RealityEvidence}"
PROOFS_TABLE="${AZURE_TABLE_PROOFS:-RealityProofs}"
DEVICES_TABLE="${AZURE_TABLE_DEVICES:-RealityDevices}"
AUDIT_LOGS_TABLE="${AZURE_TABLE_AUDIT_LOGS:-RealityAuditLogs}"
PUBLIC_WEB_BASE_URL="${PUBLIC_WEB_BASE_URL:-https://${AZURE_FUNCTION_APP_NAME}.azurewebsites.net}"
KEY_NAME="${AZURE_KEY_VAULT_KEY_NAME:-reality-proof-signing}"
APP_INSIGHTS_NAME="${AZURE_APP_INSIGHTS_NAME:-${AZURE_FUNCTION_APP_NAME}-insights}"

if ! az extension show --name application-insights --output none 2>/dev/null; then
  az extension add --name application-insights --only-show-errors
fi

az group create \
  --name "$AZURE_RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --output none

az storage account create \
  --name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false \
  --output none

storage_key="$(az storage account keys list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --query '[0].value' -o tsv)"

for container in "$EVIDENCE_CONTAINER" "$PROOFS_CONTAINER"; do
  az storage container create \
    --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
    --account-key "$storage_key" \
    --name "$container" \
    --public-access off \
    --output none
done

for table in \
  "$SESSIONS_TABLE" \
  "$EVIDENCE_TABLE" \
  "$PROOFS_TABLE" \
  "$DEVICES_TABLE" \
  "$AUDIT_LOGS_TABLE"; do
  az storage table create \
    --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
    --account-key "$storage_key" \
    --name "$table" \
    --output none
done
unset storage_key

if ! az monitor app-insights component show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --app "$APP_INSIGHTS_NAME" \
  --output none 2>/dev/null; then
  az monitor app-insights component create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --app "$APP_INSIGHTS_NAME" \
    --location "$AZURE_LOCATION" \
    --kind web \
    --application-type web \
    --output none
fi
app_insights_connection="$(az monitor app-insights component show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --app "$APP_INSIGHTS_NAME" \
  --query connectionString -o tsv)"

if ! az iot hub show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_IOT_HUB_NAME" \
  --output none 2>/dev/null; then
  if ! az iot hub create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$AZURE_IOT_HUB_NAME" \
    --location "$AZURE_LOCATION" \
    --sku F1 \
    --partition-count 2 \
    --output none; then
    if [[ "${ALLOW_IOT_HUB_S1:-false}" != "true" ]]; then
      echo "IoT Hub F1 creation failed. Review cost, then set ALLOW_IOT_HUB_S1=true to create S1." >&2
      exit 1
    fi
    az iot hub create \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --name "$AZURE_IOT_HUB_NAME" \
      --location "$AZURE_LOCATION" \
      --sku S1 \
      --partition-count 2 \
      --output none
  fi
fi

if ! az iot hub policy show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --name reality-functions-service \
  --output none 2>/dev/null; then
  az iot hub policy create \
    --hub-name "$AZURE_IOT_HUB_NAME" \
    --name reality-functions-service \
    --permissions ServiceConnect \
    --output none
fi
if ! az iot hub policy show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --name reality-functions-events \
  --output none 2>/dev/null; then
  az iot hub policy create \
    --hub-name "$AZURE_IOT_HUB_NAME" \
    --name reality-functions-events \
    --permissions ServiceConnect \
    --output none
fi
iot_host_name="$(az iot hub show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_IOT_HUB_NAME" \
  --query properties.hostName -o tsv)"
iot_service_key="$(az iot hub policy show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --name reality-functions-service \
  --query primaryKey -o tsv)"
iot_service_connection="HostName=${iot_host_name};SharedAccessKeyName=reality-functions-service;SharedAccessKey=${iot_service_key}"
event_endpoint="$(az iot hub show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_IOT_HUB_NAME" \
  --query properties.eventHubEndpoints.events.endpoint -o tsv)"
event_path="$(az iot hub show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_IOT_HUB_NAME" \
  --query properties.eventHubEndpoints.events.path -o tsv)"
event_key="$(az iot hub policy show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --name reality-functions-events \
  --query primaryKey -o tsv)"
iot_event_connection="Endpoint=${event_endpoint};SharedAccessKeyName=reality-functions-events;SharedAccessKey=${event_key};EntityPath=${event_path}"

if ! az functionapp show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_FUNCTION_APP_NAME" \
  --output none 2>/dev/null; then
  az functionapp create \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --name "$AZURE_FUNCTION_APP_NAME" \
    --storage-account "$AZURE_STORAGE_ACCOUNT_NAME" \
    --flexconsumption-location "$AZURE_LOCATION" \
    --runtime python \
    --runtime-version 3.13 \
    --functions-version 4 \
    --output none
fi

principal_id="$(az functionapp identity assign \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_FUNCTION_APP_NAME" \
  --query principalId -o tsv)"
storage_id="$(az storage account show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --query id -o tsv)"

az keyvault create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_KEY_VAULT_NAME" \
  --location "$AZURE_LOCATION" \
  --enable-rbac-authorization true \
  --enable-purge-protection true \
  --output none
vault_id="$(az keyvault show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_KEY_VAULT_NAME" \
  --query id -o tsv)"
operator_id="$(az ad signed-in-user show --query id -o tsv)"
operator_assignment_count="$(az role assignment list \
  --assignee "$operator_id" \
  --role "Key Vault Crypto Officer" \
  --scope "$vault_id" \
  --query 'length(@)' -o tsv)"
if [[ "$operator_assignment_count" == "0" ]]; then
  az role assignment create \
    --assignee-object-id "$operator_id" \
    --assignee-principal-type User \
    --role "Key Vault Crypto Officer" \
    --scope "$vault_id" \
    --output none
fi

for role in \
  "Storage Blob Data Contributor" \
  "Storage Blob Delegator" \
  "Storage Table Data Contributor"; do
  assignment_count="$(az role assignment list \
    --assignee "$principal_id" \
    --role "$role" \
    --scope "$storage_id" \
    --query 'length(@)' -o tsv)"
  if [[ "$assignment_count" == "0" ]]; then
    az role assignment create \
      --assignee-object-id "$principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" \
      --scope "$storage_id" \
      --output none
  fi
done

key_assignment_count="$(az role assignment list \
  --assignee "$principal_id" \
  --role "Key Vault Crypto User" \
  --scope "$vault_id" \
  --query 'length(@)' -o tsv)"
if [[ "$key_assignment_count" == "0" ]]; then
  az role assignment create \
    --assignee-object-id "$principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "Key Vault Crypto User" \
    --scope "$vault_id" \
    --output none
fi

if ! az keyvault key show \
  --vault-name "$AZURE_KEY_VAULT_NAME" \
  --name "$KEY_NAME" \
  --output none 2>/dev/null; then
  for attempt in {1..12}; do
    if az keyvault key create \
      --vault-name "$AZURE_KEY_VAULT_NAME" \
      --name "$KEY_NAME" \
      --kty RSA \
      --size 3072 \
      --ops sign verify \
      --output none 2>/dev/null; then
      break
    fi
    if [[ "$attempt" == "12" ]]; then
      echo "Key Vault role propagation did not complete" >&2
      exit 1
    fi
    sleep 10
  done
fi

az functionapp config appsettings set \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_FUNCTION_APP_NAME" \
  --settings \
    USE_AZURE_STORAGE=true \
    AZURE_STORAGE_ACCOUNT_NAME="$AZURE_STORAGE_ACCOUNT_NAME" \
    AZURE_BLOB_CONTAINER_EVIDENCE="$EVIDENCE_CONTAINER" \
    AZURE_BLOB_CONTAINER_PROOFS="$PROOFS_CONTAINER" \
    AZURE_TABLE_SESSIONS="$SESSIONS_TABLE" \
    AZURE_TABLE_EVIDENCE="$EVIDENCE_TABLE" \
    AZURE_TABLE_PROOFS="$PROOFS_TABLE" \
    AZURE_TABLE_DEVICES="$DEVICES_TABLE" \
    AZURE_TABLE_AUDIT_LOGS="$AUDIT_LOGS_TABLE" \
    AZURE_STORAGE_SAS_TTL_SECONDS=300 \
    TIME_LIMIT_SECONDS="${TIME_LIMIT_SECONDS:-30}" \
    GRACE_SECONDS="${GRACE_SECONDS:-15}" \
    ALLOWED_DEVICE_IDS="${ALLOWED_DEVICE_IDS:-raspi-anchor-01}" \
    ADMIN_API_KEY="$ADMIN_API_KEY" \
    ALLOW_LOCAL_DEVICE_HTTP=false \
    USE_IOT_HUB=true \
    IOT_HUB_SERVICE_CONNECTION_STRING="$iot_service_connection" \
    IOT_HUB_EVENT_CONNECTION="$iot_event_connection" \
    IOT_HUB_EVENT_HUB_NAME="$event_path" \
    IOT_HUB_CONSUMER_GROUP='$Default' \
    AzureWebJobs.iot_evidence_telemetry.Disabled=false \
    AzureWebJobsDisableHomepage=true \
    USE_AZURE_KEY_VAULT=true \
    AZURE_KEY_VAULT_URL="https://${AZURE_KEY_VAULT_NAME}.vault.azure.net" \
    AZURE_KEY_VAULT_KEY_NAME="$KEY_NAME" \
    AZURE_KEY_VAULT_KEY_VERSION="${AZURE_KEY_VAULT_KEY_VERSION:-}" \
    PUBLIC_WEB_BASE_URL="$PUBLIC_WEB_BASE_URL" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$app_insights_connection" \
  --output none

az functionapp config appsettings delete \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$AZURE_FUNCTION_APP_NAME" \
  --setting-names DEVICE_API_KEY STUB_SIGNING_SECRET SIGNATURE_KEY_ID \
  --output none

unset iot_service_key event_key iot_service_connection iot_event_connection

printf 'Provisioned %s\n' "$AZURE_FUNCTION_APP_NAME"
