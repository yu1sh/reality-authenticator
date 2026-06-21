# Reality Authenticator

Reality Authenticator records physical interaction and surrounding evidence as
an integrity-checkable evidence bundle.

This repository implements the v1.2 MVP code path:

- shared SHA-256 and canonical JSON utilities
- a local Edge Agent dry-run
- Evidence Manifest generation
- local StartSession and IngestEvidence APIs
- canonical JSON file persistence and Manifest validation
- Proof Record issuance with a local HMAC signing stub
- local Proof hash and signature verification API
- public Proof projection, QR PNG, and verification page
- Edge-to-Cloud dry-run synchronization and a local end-to-end demo
- Raspberry Pi GPIO, Grove serial sensors, Pi Camera, and USB microphone capture
- switchable local/Azure Table and Blob persistence with ETag concurrency
- direct Edge media upload through short-lived Blob SAS URLs
- Azure Functions Flex Consumption build, provision, and deploy scripts
- Azure Key Vault PS256 Proof signing with versioned RSA key IDs
- schema 1.0/1.1 verification compatibility and schema 1.2 Proof issuance
- Azure IoT Hub C2D commands and D2C evidence telemetry
- persistent Device and AuditLog records
- Japanese Home, Start, Session, Proof, and Verify pages
- per-verification Blob hash and registered-device status checks
- deterministic fixtures and pytest coverage

A custom production domain and Microsoft Entra ID remain outside the MVP.
Final acceptance additionally requires the dedicated Azure dev environment and
the specified Raspberry Pi to complete three consecutive runs within 30 seconds.

## Requirements

- Python 3.11 or newer

## Development setup

```bash
python -m venv .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install \
  -e packages/reality-core \
  -e edge-agent \
  -e cloud-functions \
  pytest
```

## Run the dry-run

```bash
.venv/bin/python -m reality_edge.main --dry-run
```

The command creates an evidence bundle below `./output/<session-id>/` and
prints the manifest path and SHA-256 digest.

Interactive button capture is also available:

```bash
.venv/bin/python -m reality_edge.main --dry-run --interactive
```

## Run the Phase 5 end-to-end demo

Azure Functions Core Tools 4.x is required for the one-command HTTP demo.

```bash
cp cloud-functions/local.settings.json.example \
  cloud-functions/local.settings.json
./scripts/demo_phase5.sh
```

The script starts the local Function host when necessary, runs:

```text
StartSession → dry-run evidence → IngestEvidence → IssueProof → VerifyProof
```

It prints the Proof ID, verification page URL, and QR URL. A Function host
started by the script remains running until Ctrl-C so the page can be opened.

To run Edge sync against an already running host:

```bash
API_BASE_URL=http://localhost:7071/api \
VERIFY_BASE_URL=http://localhost:7071 \
DEVICE_API_KEY=local-demo-device-key \
.venv/bin/python -m reality_edge.main --dry-run --cloud-sync
```

## Run tests

```bash
.venv/bin/python -m pytest \
  packages/reality-core/tests \
  edge-agent/tests \
  cloud-functions/tests \
  integration-tests
```

## Run on Raspberry Pi

Phase 6 targets Raspberry Pi 4 with Raspberry Pi OS Lite 64-bit. Install the
OS and hardware dependencies:

```bash
./scripts/setup_raspberry_pi.sh
```

For local HTTP development only, configure the same-LAN Function host URL,
Grove serial device, USB microphone, and local device API key. Run:

```bash
.venv/bin/python -m reality_edge.main \
  --real-device --cloud-sync \
  --evidence-dir /home/pi/reality-evidence
```

For the Azure dev acceptance path, use the IoT Hub device connection string
written by `scripts/azure/register_device.sh` and run the listener instead:

```bash
set -a
source edge-agent/.env
set +a
.venv/bin/python -m reality_edge.main \
  --real-device --iot-listen \
  --evidence-dir /home/pi/reality-evidence
```

See [docs/RASPBERRY_PI_SETUP.md](docs/RASPBERRY_PI_SETUP.md) for wiring,
Arduino firmware, diagnostics, and failure handling.

## Run the local APIs

Azure Functions Core Tools 4.x is required to expose the HTTP endpoints:

```bash
cd cloud-functions
cp local.settings.json.example local.settings.json
../.venv/bin/python -m pip install -e .
func start
```

Start a session:

```bash
curl -X POST http://localhost:7071/api/sessions/start \
  -H 'Content-Type: application/json' \
  -H 'X-Device-Api-Key: local-demo-device-key' \
  -d '{"device_id":"raspi-anchor-01"}'
```

Ingest a Phase 1 Evidence Manifest:

```bash
curl -X POST http://localhost:7071/api/evidence/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-Device-Api-Key: local-demo-device-key' \
  --data-binary @../output/<session-id>/manifest.json
```

Issue a Proof after evidence is accepted:

```bash
curl -X POST http://localhost:7071/api/proofs/issue \
  -H 'Content-Type: application/json' \
  -H 'X-Device-Api-Key: local-demo-device-key' \
  -d '{"session_id":"<session-id>"}'
```

Verify the saved Proof:

```bash
curl -X POST \
  http://localhost:7071/api/proofs/<proof-id>/verify
```

Open the public verification page:

```text
http://localhost:7071/verify/<proof-id>
```

The public JSON and QR endpoints are:

```text
GET /api/proofs/<proof-id>
GET /api/proofs/<proof-id>/qr
```

Local Session, Manifest, and Proof records are written below
`cloud-functions/.local-data/`. Set `STUB_SIGNING_SECRET` only to a local
development value. The `STUB-HS256` result is not a Key Vault electronic
signature. New local Proofs use schema 1.2 but remain clearly labelled
`STUB-HS256`. Local mode does not verify image/audio bytes; Azure mode verifies
their size, Content-Type, and SHA-256 before accepting evidence.

## Deploy Phase 7-8 to Azure

The Azure deployment targets Flex Consumption with Python 3.13. It uses
private Blob containers, Azure Tables, Managed Identity, IoT Hub,
Application Insights, and short-lived write-only media upload SAS URLs.
Proofs use an RSA 3072 Key Vault key and PS256 signatures.

```bash
./scripts/azure/provision_phase7.sh
./scripts/azure/register_device.sh
./scripts/azure/deploy_phase7.sh
```

Run three simulated IoT device acceptance cycles:

```bash
SMOKE_RUNS=3 ./scripts/azure/smoke_test.sh
```

See [docs/AZURE_DEPLOYMENT.md](docs/AZURE_DEPLOYMENT.md) for required
environment variables, RBAC, build constraints, smoke tests, and secret
handling. See [docs/ACCEPTANCE_STATUS.md](docs/ACCEPTANCE_STATUS.md) for the
current requirement-by-requirement acceptance evidence.

See [docs/spec.md](docs/spec.md) for the full system specification and
[docs/PLAN_PHASE_1.md](docs/PLAN_PHASE_1.md) and
[docs/PLAN_PHASE_2.md](docs/PLAN_PHASE_2.md), and
[docs/PLAN_PHASE_3.md](docs/PLAN_PHASE_3.md),
[docs/PLAN_PHASE_4.md](docs/PLAN_PHASE_4.md), and
[docs/PLAN_PHASE_5.md](docs/PLAN_PHASE_5.md), and
[docs/PLAN_PHASE_6.md](docs/PLAN_PHASE_6.md), and
[docs/PLAN_PHASE_7.md](docs/PLAN_PHASE_7.md), and
[docs/PLAN_PHASE_8.md](docs/PLAN_PHASE_8.md) for the implementation plans.
