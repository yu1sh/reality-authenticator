#!/usr/bin/env bash
set -euo pipefail

: "${AZURE_IOT_HUB_NAME:?set AZURE_IOT_HUB_NAME}"
: "${AZURE_RESOURCE_GROUP:?set AZURE_RESOURCE_GROUP}"
: "${AZURE_STORAGE_ACCOUNT_NAME:?set AZURE_STORAGE_ACCOUNT_NAME}"
DEVICE_ID="${DEVICE_ID:-raspi-anchor-01}"
DISPLAY_NAME="${DEVICE_DISPLAY_NAME:-Raspberry Pi Anchor 01}"
DEVICES_TABLE="${AZURE_TABLE_DEVICES:-RealityDevices}"
OUTPUT_ENV_FILE="${OUTPUT_ENV_FILE:-edge-agent/.env}"

if ! az extension show --name azure-iot --output none 2>/dev/null; then
  az extension add --name azure-iot --only-show-errors
fi

if ! az iot hub device-identity show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --device-id "$DEVICE_ID" \
  --output none 2>/dev/null; then
  az iot hub device-identity create \
    --hub-name "$AZURE_IOT_HUB_NAME" \
    --device-id "$DEVICE_ID" \
    --auth-method shared_private_key \
    --output none
fi

connection_string="$(az iot hub device-identity connection-string show \
  --hub-name "$AZURE_IOT_HUB_NAME" \
  --device-id "$DEVICE_ID" \
  --query connectionString -o tsv)"

storage_key="$(az storage account keys list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --query '[0].value' -o tsv)"
if ! az storage entity show \
  --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --account-key "$storage_key" \
  --table-name "$DEVICES_TABLE" \
  --partition-key DEVICE \
  --row-key "$DEVICE_ID" \
  --output none 2>/dev/null; then
  created_at="$(date -u '+%Y-%m-%dT%H:%M:%S.000+00:00')"
  canonical_json="$(python3 -c \
    'import json,sys; print(json.dumps({"device_id":sys.argv[1],"display_name":sys.argv[2],"status":"active","created_at":sys.argv[3],"last_seen_at":None,"iot_hub_device_id":sys.argv[1],"public_note":""},ensure_ascii=False,sort_keys=True,separators=(",",":")))' \
    "$DEVICE_ID" "$DISPLAY_NAME" "$created_at")"
  az storage entity insert \
    --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
    --account-key "$storage_key" \
    --table-name "$DEVICES_TABLE" \
    --entity \
      PartitionKey=DEVICE \
      RowKey="$DEVICE_ID" \
      canonical_json="$canonical_json" \
      device_id="$DEVICE_ID" \
      status=active \
      display_name="$DISPLAY_NAME" \
      created_at="$created_at" \
      last_seen_at= \
      iot_hub_device_id="$DEVICE_ID" \
      public_note= \
    --output none
fi

mkdir -p "$(dirname "$OUTPUT_ENV_FILE")"
umask 077
printf 'DEVICE_ID=%s\nIOT_HUB_DEVICE_CONNECTION_STRING=%s\n' \
  "$DEVICE_ID" "$connection_string" > "$OUTPUT_ENV_FILE"
chmod 600 "$OUTPUT_ENV_FILE"
unset connection_string storage_key canonical_json

printf 'Registered %s in IoT Hub and Devices Table; wrote its secret to %s\n' \
  "$DEVICE_ID" "$OUTPUT_ENV_FILE"
