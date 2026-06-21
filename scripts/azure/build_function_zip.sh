#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_ROOT="$ROOT_DIR/cloud-functions/.deployment"
APP_DIR="$BUILD_ROOT/app"
ZIP_PATH="$BUILD_ROOT/reality-authenticator-functions.zip"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEPLOY_PYTHON_VERSION="${DEPLOY_PYTHON_VERSION:-3.13}"
DEPLOY_PYTHON_TAG="${DEPLOY_PYTHON_VERSION//./}"
PIP_PLATFORM="${PIP_PLATFORM:-manylinux_2_28_x86_64}"
PIP_FALLBACK_PLATFORM="${PIP_FALLBACK_PLATFORM:-manylinux2014_x86_64}"

rm -rf "$APP_DIR" "$ZIP_PATH"
mkdir -p "$APP_DIR/.python_packages/lib/site-packages"

"$PYTHON_BIN" -m pip install \
  --disable-pip-version-check \
  --target "$APP_DIR/.python_packages/lib/site-packages" \
  --platform "$PIP_PLATFORM" \
  --platform "$PIP_FALLBACK_PLATFORM" \
  --implementation cp \
  --python-version "$DEPLOY_PYTHON_VERSION" \
  --abi "cp${DEPLOY_PYTHON_TAG}" \
  --only-binary=:all: \
  -r "$ROOT_DIR/cloud-functions/requirements.txt"

cp -R \
  "$ROOT_DIR/packages/reality-core/src/reality_core" \
  "$APP_DIR/.python_packages/lib/site-packages/"
cp "$ROOT_DIR/cloud-functions/function_app.py" "$APP_DIR/"
cp "$ROOT_DIR/cloud-functions/host.json" "$APP_DIR/"
cp -R "$ROOT_DIR/cloud-functions/reality_cloud" "$APP_DIR/"
cp -R "$ROOT_DIR/cloud-functions/web" "$APP_DIR/"

find "$APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find \
  "$APP_DIR/.python_packages/lib/site-packages" \
  -type d -name tests -prune -exec rm -rf {} +
find "$APP_DIR" -type f -name '*.pyc' -delete

"$PYTHON_BIN" - "$APP_DIR" "$ZIP_PATH" "$DEPLOY_PYTHON_TAG" <<'PY'
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
import sys

root = Path(sys.argv[1])
destination = Path(sys.argv[2])
target_python_tag = sys.argv[3]
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root))

with ZipFile(destination) as archive:
    names = set(archive.namelist())
    required = {
        "function_app.py",
        "host.json",
        "web/verify.html",
        "web/verify.css",
        "web/app.html",
        "web/app.css",
        "web/app.js",
    }
    missing = required - names
    forbidden = [
        name for name in names
        if "local.settings.json" in name
        or "/tests/" in f"/{name}"
    ]
    incompatible_native = [
        name
        for name in names
        if (
            (match := re.search(r"\.cpython-(\d+)", name))
            and match.group(1) != target_python_tag
        )
    ]
    if missing or forbidden or incompatible_native:
        raise SystemExit(
            "invalid deployment ZIP: "
            f"missing={missing}, forbidden={forbidden}, "
            f"incompatible_native={incompatible_native}"
        )
PY

printf 'Built %s\n' "$ZIP_PATH"
