#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
SETTINGS="$ROOT_DIR/cloud-functions/local.settings.json"
API_BASE_URL="${API_BASE_URL:-http://localhost:7071/api}"
VERIFY_BASE_URL="${VERIFY_BASE_URL:-http://localhost:7071}"
FUNC_PID=""

cleanup() {
  if [[ -n "$FUNC_PID" ]] && kill -0 "$FUNC_PID" 2>/dev/null; then
    kill "$FUNC_PID"
    wait "$FUNC_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "$PYTHON" ]]; then
  echo "error: create .venv and install the project first" >&2
  exit 1
fi
if [[ ! -f "$SETTINGS" ]]; then
  echo "error: copy cloud-functions/local.settings.json.example to local.settings.json" >&2
  exit 1
fi

DEVICE_API_KEY="$(
  "$PYTHON" -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["Values"].get("DEVICE_API_KEY", ""))' \
    "$SETTINGS"
)"
if [[ -z "$DEVICE_API_KEY" ]]; then
  echo "error: DEVICE_API_KEY is missing from local.settings.json" >&2
  exit 1
fi

if ! curl --silent --max-time 1 --output /dev/null \
  "$VERIFY_BASE_URL/verify/phase5-readiness"; then
  if ! command -v func >/dev/null 2>&1; then
    echo "error: Azure Functions Core Tools 4.x (func) is required" >&2
    exit 1
  fi
  (
    cd "$ROOT_DIR/cloud-functions"
    exec func start --port 7071
  ) >"/tmp/reality-authenticator-phase5-func.log" 2>&1 &
  FUNC_PID=$!

  for _ in {1..30}; do
    if curl --silent --max-time 1 --output /dev/null \
      "$VERIFY_BASE_URL/verify/phase5-readiness"; then
      break
    fi
    if ! kill -0 "$FUNC_PID" 2>/dev/null; then
      echo "error: Function host exited; see /tmp/reality-authenticator-phase5-func.log" >&2
      exit 1
    fi
    sleep 1
  done
  if ! curl --silent --max-time 1 --output /dev/null \
    "$VERIFY_BASE_URL/verify/phase5-readiness"; then
    echo "error: Function host did not become ready" >&2
    exit 1
  fi
fi

API_BASE_URL="$API_BASE_URL" \
VERIFY_BASE_URL="$VERIFY_BASE_URL" \
DEVICE_API_KEY="$DEVICE_API_KEY" \
CLOUD_SYNC_ENABLED=true \
"$PYTHON" -m reality_edge.main --dry-run --cloud-sync

if [[ -n "$FUNC_PID" ]]; then
  echo "Function host remains available for verification. Press Ctrl-C to stop."
  wait "$FUNC_PID"
fi
