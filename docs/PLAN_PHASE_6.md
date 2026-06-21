# Reality Authenticator Phase 6 Implementation Plan

## Goal

Run the Edge Agent on Raspberry Pi 4 with a GPIO button and LED, Grove sensors
over Arduino USB serial, Pi Camera, and a USB microphone. Reuse the Phase 5
Cloud synchronization and verification page without changing Manifest schema
`1.0`.

## Hardware capture

- `--real-device` performs preflight checks before requesting a Session.
- GPIO Zero records active-low BCM17 button presses with 200ms debounce and
  drives a BCM27 status LED.
- Grove firmware for DHT11 and DHT20 emits the same one-line JSON protocol.
- `rpicam-still` creates a 1280x720 JPEG and `arecord` creates mono 16-bit
  16kHz WAV.
- Button, sensors, camera, and microphone run concurrently and must complete
  before Session expiry.

## Compatibility

Dry-run remains hardware-independent. Hardware libraries are lazy-loaded and
pyserial is an optional Raspberry Pi dependency. Disabled media use fixtures
only for local diagnostics and cannot be synchronized to Cloud.

Cloud time and grace limits are environment-configurable. Existing defaults
remain 10 and 5 seconds; the real-device example uses 30 and 15 seconds.

## Verification

Unit tests inject GPIO, serial, subprocess, clock, and status fakes. They cover
timeouts, invalid sensor data, empty media, failure logging, and complete
real-device Manifest construction without Raspberry Pi hardware.

Azure production services, IoT Hub, Blob Storage, Key Vault, systemd, legal
certificates, biometrics, and proof of AI non-use remain deferred.
