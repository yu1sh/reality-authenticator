#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${PUBLIC_WEB_BASE_URL:?set PUBLIC_WEB_BASE_URL}"
: "${ADMIN_API_KEY:?set ADMIN_API_KEY}"
: "${IOT_HUB_DEVICE_CONNECTION_STRING:?set IOT_HUB_DEVICE_CONNECTION_STRING}"
: "${AZURE_RESOURCE_GROUP:?set AZURE_RESOURCE_GROUP}"
: "${AZURE_STORAGE_ACCOUNT_NAME:?set AZURE_STORAGE_ACCOUNT_NAME}"
: "${AZURE_FUNCTION_APP_NAME:?set AZURE_FUNCTION_APP_NAME}"

RUNS="${SMOKE_RUNS:-3}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-30}"
DEVICE_ID="${DEVICE_ID:-raspi-anchor-01}"
AUDIT_LOGS_TABLE="${AZURE_TABLE_AUDIT_LOGS:-RealityAuditLogs}"
APP_INSIGHTS_NAME="${AZURE_APP_INSIGHTS_NAME:-${AZURE_FUNCTION_APP_NAME}-insights}"
EDGE_PID=""
SMOKE_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if ! [[ "$RUNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "SMOKE_RUNS must be a positive integer" >&2
  exit 1
fi
if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "SMOKE_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 1
fi

if ! az extension show --name application-insights --output none 2>/dev/null; then
  az extension add --name application-insights --only-show-errors
fi

storage_key="$(az storage account keys list \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
  --query '[0].value' -o tsv)"

cleanup() {
  if [[ -n "$EDGE_PID" ]] && kill -0 "$EDGE_PID" 2>/dev/null; then
    kill "$EDGE_PID"
    wait "$EDGE_PID" 2>/dev/null || true
  fi
  unset storage_key
}
trap cleanup EXIT INT TERM

IOT_HUB_DEVICE_CONNECTION_STRING="$IOT_HUB_DEVICE_CONNECTION_STRING" \
DEVICE_ID="$DEVICE_ID" \
"$ROOT_DIR/.venv/bin/python" -m reality_edge.main \
  --dry-run --iot-listen >"/tmp/reality-iot-edge.log" 2>&1 &
EDGE_PID=$!
sleep 3

for _run in $(seq 1 "$RUNS"); do
  run_started=$SECONDS
  response="$(curl --fail --silent \
    -X POST "$PUBLIC_WEB_BASE_URL/api/sessions/start" \
    -H "X-Admin-Api-Key: $ADMIN_API_KEY" \
    -H 'Content-Type: application/json' \
    -d "{\"device_id\":\"$DEVICE_ID\"}")"
  session_id="$("$ROOT_DIR/.venv/bin/python" -c \
    'import json,sys; print(json.load(sys.stdin)["session_id"])' <<<"$response")"

  proof_id=""
  while (( SECONDS - run_started < TIMEOUT_SECONDS )); do
    status_json="$(curl --fail --silent \
      "$PUBLIC_WEB_BASE_URL/api/sessions/$session_id" \
      -H "X-Admin-Api-Key: $ADMIN_API_KEY")"
    status="$("$ROOT_DIR/.venv/bin/python" -c \
      'import json,sys; print(json.load(sys.stdin)["status"])' <<<"$status_json")"
    if [[ "$status" == "proof_issued" ]]; then
      proof_id="$("$ROOT_DIR/.venv/bin/python" -c \
        'import json,sys; print(json.load(sys.stdin)["proof_id"])' <<<"$status_json")"
      break
    fi
    if [[ "$status" == "failed" ]]; then
      echo "Session $session_id failed" >&2
      exit 1
    fi
    sleep 1
  done
  if [[ -z "$proof_id" ]]; then
    echo "Session $session_id did not issue a Proof" >&2
    exit 1
  fi
  proof_elapsed=$((SECONDS - run_started))
  if (( proof_elapsed > TIMEOUT_SECONDS )); then
    echo "Session $session_id exceeded ${TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  verification="$(curl --fail --silent \
    -X POST "$PUBLIC_WEB_BASE_URL/api/proofs/$proof_id/verify")"
  "$ROOT_DIR/.venv/bin/python" -c \
    'import json,sys; value=json.load(sys.stdin); assert value["status"] == "VALID", value; assert all(value["checks"].values()), value' \
    <<<"$verification"
  proof="$(curl --fail --silent \
    "$PUBLIC_WEB_BASE_URL/api/proofs/$proof_id")"
  "$ROOT_DIR/.venv/bin/python" -c \
    'import json,sys; value=json.load(sys.stdin); assert value["schema_version"] == "1.2", value; assert value["signature_algorithm"] == "PS256", value; assert "/keys/" in value["key_id"], value; assert value["public_key"]["bits"] >= 3072, value' \
    <<<"$proof"
  qr_path="/tmp/reality-authenticator-${proof_id}.png"
  curl --fail --silent \
    "$PUBLIC_WEB_BASE_URL/api/proofs/$proof_id/qr" \
    --output "$qr_path"
  "$ROOT_DIR/.venv/bin/python" -c \
    'from pathlib import Path; import sys; assert Path(sys.argv[1]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")' \
    "$qr_path"
  audit_json="$(az storage entity query \
    --account-name "$AZURE_STORAGE_ACCOUNT_NAME" \
    --account-key "$storage_key" \
    --table-name "$AUDIT_LOGS_TABLE" \
    --filter "session_id eq '$session_id'" \
    --output json)"
  "$ROOT_DIR/.venv/bin/python" -c \
    'import json,sys; value=json.load(sys.stdin); rows=value if isinstance(value,list) else value.get("items",[]); events={row.get("event_type") for row in rows}; required={"session_created","device_command_dispatched","evidence_ingested","proof_issued","proof_verified"}; missing=required-events; assert not missing, f"missing AuditLog events: {sorted(missing)}"' \
    <<<"$audit_json"
  printf 'Run %s: %s VALID, Proof issued in %ss\n' \
    "$_run" "$proof_id" "$proof_elapsed"
done

app_id="$(az monitor app-insights component show \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --app "$APP_INSIGHTS_NAME" \
  --query appId -o tsv)"
minimum_requests=$((RUNS * 2))
observed_requests=0
for _attempt in $(seq 1 12); do
  insights_json="$(az monitor app-insights query \
    --apps "$app_id" \
    --analytics-query \
      "requests | where timestamp >= datetime(${SMOKE_STARTED_AT}) | where success == true | where url has \"/api/sessions/start\" or url has \"/api/proofs/\" | summarize total=count()" \
    --offset 30m \
    --output json)"
  observed_requests="$("$ROOT_DIR/.venv/bin/python" -c \
    'import json,sys; value=json.load(sys.stdin); print(value.get("tables",[{"rows":[[0]]}])[0].get("rows",[[0]])[0][0])' \
    <<<"$insights_json")"
  if [[ "$observed_requests" =~ ^[0-9]+$ ]] \
    && (( observed_requests >= minimum_requests )); then
    break
  fi
  sleep 10
done
if ! [[ "$observed_requests" =~ ^[0-9]+$ ]] \
  || (( observed_requests < minimum_requests )); then
  echo "Application Insights did not expose the expected requests in time" >&2
  exit 1
fi

printf 'Acceptance complete: %s consecutive runs, AuditLog complete, Application Insights requests=%s\n' \
  "$RUNS" "$observed_requests"
