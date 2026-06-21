#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "warning: expected a 64-bit Raspberry Pi OS host" >&2
fi

sudo apt update
sudo apt install -y \
  python3-venv \
  python3-gpiozero \
  python3-lgpio \
  alsa-utils \
  rpicam-apps-lite \
  git

python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install \
  -e "$ROOT_DIR/packages/reality-core" \
  -e "$ROOT_DIR/edge-agent[raspberry-pi]"

sudo usermod -aG gpio,audio,video,dialout "$USER"

cat <<EOF
Raspberry Pi dependencies are installed.

Next:
1. Log out and back in so group membership is refreshed.
2. Upload one Grove firmware sketch from edge-agent/firmware/.
3. Create .env and set GROVE_SERIAL_PORT, AUDIO_DEVICE, DEVICE_ID, and
   IOT_HUB_DEVICE_CONNECTION_STRING.
4. Follow docs/RASPBERRY_PI_SETUP.md for diagnostics and the demo command.
EOF
