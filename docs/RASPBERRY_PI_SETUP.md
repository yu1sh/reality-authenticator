# Raspberry Pi Phase 6 Setup

## Standard hardware

- Raspberry Pi 4 with Raspberry Pi OS Lite 64-bit Trixie
- official Raspberry Pi CSI camera
- USB Audio Class microphone
- push button between BCM GPIO17 and GND
- LED on BCM GPIO27 through a current-limiting resistor to GND
- Grove Beginner Kit for Arduino connected by USB

The button uses the internal pull-up and is active-low. GPIO numbers are BCM
numbers, not physical header positions.

## Install

```bash
git clone <repository-url> reality-authenticator
cd reality-authenticator
./scripts/setup_raspberry_pi.sh
```

Log out and back in after setup so membership in `gpio`, `audio`, `video`, and
`dialout` takes effect.

## Grove firmware

Upload one sketch with Arduino IDE:

- old kit with DHT11:
  `edge-agent/firmware/grove_bridge_dht11/grove_bridge_dht11.ino`
- kit dated October 2025 or later with DHT20:
  `edge-agent/firmware/grove_bridge_dht20/grove_bridge_dht20.ino`

Install the Arduino DHT sensor library for DHT11 or the DHT20 library for the
new kit. Both sketches listen at 115200bps. The Pi sends `READ` and receives
one JSON line containing temperature, humidity, light A6, and sound A2.

Find the stable serial path:

```bash
ls -l /dev/serial/by-id/
```

## Configure

Create a local `.env` and export it into the shell before running:

```env
DEVICE_ID=raspi-anchor-01
EVIDENCE_DIR=/home/pi/reality-evidence
IOT_HUB_DEVICE_CONNECTION_STRING=<device-connection-string>
IOT_HEARTBEAT_SECONDS=60
GROVE_SERIAL_PORT=/dev/serial/by-id/<arduino-device>
GROVE_STARTUP_DELAY_SECONDS=2
AUDIO_DEVICE=plughw:1,0
BUTTON_GPIO=17
LED_GPIO=27
```

```bash
set -a
source .env
set +a
```

`register_device.sh` writes the Azure IoT Hub device secret to
`edge-agent/.env` by default. Keep that file only on the Raspberry Pi.

For local HTTP development, also set `API_BASE_URL`, `VERIFY_BASE_URL`, and
`DEVICE_API_KEY` to the same-LAN Function host. Do not use `localhost` across
devices. These HTTP settings are not used by the Azure `--iot-listen` path.

## Diagnostics

```bash
rpicam-still --list-cameras
rpicam-still --nopreview --timeout 1000 --output /tmp/camera-test.jpg
arecord --list-devices
arecord --device plughw:1,0 --format S16_LE --rate 16000 \
  --channels 1 --duration 3 --file-type wav /tmp/mic-test.wav
```

Confirm the configured user can access `/dev/gpiochip*`, the camera, audio
device, and Grove serial port without `sudo`.

## Run

Local hardware diagnostic with fixture audio:

```bash
.venv/bin/python -m reality_edge.main \
  --real-device --no-microphone \
  --evidence-dir /home/pi/reality-evidence
```

Fixture substitution is clearly logged as degraded and cannot be used with
Cloud sync.

Complete Azure IoT Hub demo:

```bash
set -a
source edge-agent/.env
set +a
.venv/bin/python -m reality_edge.main \
  --real-device --iot-listen \
  --evidence-dir /home/pi/reality-evidence
```

The process remains online and waits for Web StartSession commands. Follow the
printed challenge, press the physical button the requested number of times,
and read the four-digit voice code. The Web Session page moves to the issued
Proof automatically. `edge.log` records capture and IoT synchronization
success or failure. An unfinished command retry reuses the matching local
Manifest rather than repeating the physical capture.

## Common failures

- `ERR_GPIO_UNAVAILABLE`: check wiring, `gpio` group, and `/dev/gpiochip*`.
- `ERR_SENSOR_UNAVAILABLE`: check `/dev/serial/by-id`, firmware, and `dialout`.
- `ERR_SENSOR_INVALID`: check DHT library and whether all analog values are 0.
- `ERR_CAMERA_CAPTURE`: run `rpicam-still --list-cameras`.
- `ERR_MICROPHONE_CAPTURE`: run `arecord --list-devices` and update the device.
- `ERR_CLOUD_UNAVAILABLE`: check LAN address, firewall, and Function host.
- `ERR_UNAUTHORIZED`: make the Edge and Cloud device API keys identical.
- `ERR_SESSION_EXPIRED`: increase the configured Cloud demo timeout or finish
  the physical challenge sooner.
