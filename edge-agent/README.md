# Reality Edge Agent

The Edge Agent runs without Raspberry Pi hardware, produces a local evidence
bundle, and can synchronize the dry-run through the Phase 5 Cloud APIs.

```bash
python -m reality_edge.main --dry-run
```

Use `--interactive` to record each Enter key press as a button event. The
default non-interactive mode is deterministic when fixed session and time
arguments are supplied, making it suitable for automated tests.

Cloud sync:

```bash
API_BASE_URL=http://localhost:7071/api \
DEVICE_API_KEY=local-demo-device-key \
VERIFY_BASE_URL=http://localhost:7071 \
python -m reality_edge.main --dry-run --cloud-sync
```

Cloud sync uses the Session ID and challenge returned by StartSession, sends
the Manifest to IngestEvidence, issues a Proof, verifies it, and prints the
verification page and QR URLs. `--session-id`, `--fixed-time`, and
`--button-count` are offline-only options.

Raspberry Pi real-device capture against the local HTTP development APIs:

```bash
python -m reality_edge.main \
  --real-device --cloud-sync \
  --evidence-dir /home/pi/reality-evidence
```

This mode performs GPIO, Grove serial, Pi Camera, USB microphone, and output
directory preflight checks before local StartSession. `--no-camera` and
`--no-microphone` provide fixture-backed local diagnostics, but are rejected
with `--cloud-sync`.

Hardware dependencies are kept outside the normal development dependency set:

```bash
pip install -e '.[raspberry-pi]'
```

Full setup and wiring instructions are in `docs/RASPBERRY_PI_SETUP.md`.

Production IoT Hub listener:

```bash
set -a
source edge-agent/.env
set +a
python -m reality_edge.main --real-device --iot-listen
```

It sends 60-second heartbeats, receives C2D StartSession commands, rejects
duplicate command IDs, uploads media with scoped SAS URLs, and sends the
Manifest as D2C telemetry. If an unfinished command is delivered again after a
temporary upload or telemetry failure, the matching local Manifest is reused
without recapturing physical evidence.
