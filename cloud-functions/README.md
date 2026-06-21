# Reality Authenticator Cloud Functions

Phase 2 through Phase 8 provide HTTP-triggered Azure Functions using the
Python v2 programming model:

- `POST /api/sessions/start`
- `GET /api/devices`
- `GET /api/sessions/{session_id}`
- `GET /api/admin/proofs/{proof_id}`
- `POST /api/evidence/ingest`
- `POST /api/proofs/issue`
- `POST /api/proofs/{proof_id}/verify`
- `GET /api/proofs/{proof_id}`
- `GET /api/proofs/{proof_id}/qr`
- `GET /`
- `GET /start`
- `GET /session/{session_id}`
- `GET /proof/{proof_id}`
- `GET /verify/{proof_id}`
- `GET /assets/app.css`
- `GET /assets/app.js`
- `GET /assets/verify.css`

## Setup

Use Python 3.13 for Azure Flex Consumption deployment. Local tests also run on newer supported
development interpreters.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ../packages/reality-core -e . pytest
cp local.settings.json.example local.settings.json
```

Replace the example `STUB_SIGNING_SECRET` in `local.settings.json` with a
local-only value before using the Proof APIs. StartSession and IngestEvidence
do not require the signing setting.

Azure StartSession and administrator APIs require `X-Admin-Api-Key`.
Local StartSession, IngestEvidence, and IssueProof may use
`X-Device-Api-Key` only while `ALLOW_LOCAL_DEVICE_HTTP=true`.
Public Proof, VerifyProof, QR, verification page, and CSS routes remain
anonymous.

Set `PUBLIC_WEB_BASE_URL` to the externally reachable origin used in QR codes.
For local development, keep the default `http://localhost:7071`.
For a Raspberry Pi on the same LAN, use the Cloud PC LAN address and set
`TIME_LIMIT_SECONDS=30` and `GRACE_SECONDS=15`. Code defaults remain 10 and 5
seconds for backward compatibility.

`requirements.txt` contains the Azure Functions runtime dependency. The shared
monorepo package is installed explicitly from `../packages/reality-core` so the
same implementation is used by Edge and Cloud code.

Run tests from the repository root:

```bash
.venv/bin/python -m pytest cloud-functions/tests
```

With Azure Functions Core Tools 4.x installed:

```bash
func start
```

Local Session, Manifest, and Proof records are canonical JSON files below
`LOCAL_DATA_DIR`. Do not commit that directory or `local.settings.json`.

Set `USE_AZURE_STORAGE=true` to use Azure Tables for Session/Evidence/Proof
indexes and private Blob containers for media, canonical Manifests, and Proof
Records. Configure either `AZURE_STORAGE_CONNECTION_STRING` or
`AZURE_STORAGE_ACCOUNT_NAME`; the latter uses `DefaultAzureCredential` and is
the production path. See [Azure deployment](../docs/AZURE_DEPLOYMENT.md).

With `USE_AZURE_KEY_VAULT=false`, Proofs use HMAC-SHA256 labelled
`STUB-HS256`; this remains a local development mechanism. With
`USE_AZURE_KEY_VAULT=true`, Proofs use schema 1.2 and PS256 with a versioned
Key Vault key ID. Key Vault failures are fail-closed and never fall back to the
stub. Schema 1.0 stub Proofs remain verifiable.

The public page excludes Session and Evidence IDs, challenge nonce and voice
code, storage paths, and media. It includes the versioned signing key ID and
public-key metadata needed to describe the signature. It is server-rendered
without client-side JavaScript or external assets.

Phase 5 Manifests may include a `challenge` snapshot containing the public
StartSession challenge fields. Cloud validates that snapshot against the
Session. Older schema `1.0` Manifests without it remain supported.
