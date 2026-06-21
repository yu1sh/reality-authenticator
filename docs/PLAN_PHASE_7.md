# Reality Authenticator Phase 7 Implementation Plan

Historical note: this document describes the Phase 7 storage/deployment slice.
The final MVP scope is defined by `docs/spec.md` v1.2 and includes later
Key Vault, IoT Hub, Web UI, Device, AuditLog, and acceptance work.

## Scope

Phase 7 prepares the Cloud application for Azure Functions Flex Consumption.
Local JSON persistence remains the default, while Azure mode stores Session,
Evidence result, and Proof indexes in Table Storage and immutable canonical
records and media in private Blob containers.

Not included in this Phase 7 slice: Key Vault signing, IoT Hub, production
domain setup, strict user authentication, Cosmos DB support, legal electronic
certificates, or proof that AI was not used.

## Storage contracts

`StorageRepository` exposes Session create/load/ETag replace, Manifest and
Proof persistence, Evidence result persistence, upload target creation, and
media verification. `StoredRecord` carries the decoded record and ETag.

Local mode retains atomic canonical JSON files. Its ETag is the SHA-256 of the
canonical Session and media verification remains false.

Azure mode uses:

| Store | Partition / path | Content |
|---|---|---|
| Sessions Table | `SESSION` / session ID | canonical Session plus query fields |
| Evidence Table | `EVIDENCE` / session ID | ingest status, failure, hash, verification |
| Proofs Table | `PROOF` / proof ID | Proof index and canonical JSON |
| Evidence Blob | `evidence/<session_id>/` | image, audio, Manifest |
| Proof Blob | `proofs/<proof_id>.json` | canonical Proof Record |

Azure SDK exceptions are translated into storage conflict, unavailable, or
corrupt errors. Handlers do not depend on SDK types.

## Upload and ingest flow

Azure StartSession adds five-minute HTTPS SAS upload targets for image and
audio. Permissions are create/write only and scoped to a single private blob.
Edge uploads both files with `BlockBlob`, Content-Type, and
an idempotent PUT, then calls IngestEvidence. A retry writes the same bytes to
the same scoped Blob so an unfinished command can converge without recapture.

IngestEvidence streams each Blob and compares the Manifest path, Content-Type,
`size_bytes`, and SHA-256. It saves the canonical Manifest and Evidence result,
then conditionally changes the Session to `evidence_uploaded` with
`evidence_bytes_verified: true`.

Local mode returns no upload object and preserves the Phase 6 flow.

## Proof concurrency

Proof issue uses an ETag transition:

```text
evidence_uploaded -> validating -> verified -> proof_issued
```

Concurrent requests reload after conflicts and converge on the reserved Proof.
An existing identical Proof save is idempotent; different content conflicts.
An interrupted proof reservation is represented by `proof_id` and signing
metadata while the public Session status remains `verified`. Legacy
`proof_issuing` records are resumed for compatibility.

## Deployment

The app remains an Azure Functions Python v2 decorator application. Route
parameters are read from `HttpRequest.route_params` while direct-call test
compatibility is retained.

`build_function_zip.sh` produces a ZIP containing the Function project, web
assets, shared `reality-core`, and dependencies under `.python_packages`.
Provisioning creates Flex Consumption, Storage resources, Managed Identity,
RBAC, and app settings. Deployment uses Azure CLI config-zip.

## Configuration

```env
USE_AZURE_STORAGE=false
AZURE_STORAGE_CONNECTION_STRING=
AZURE_STORAGE_ACCOUNT_NAME=
AZURE_BLOB_CONTAINER_EVIDENCE=reality-evidence
AZURE_BLOB_CONTAINER_PROOFS=reality-proofs
AZURE_TABLE_SESSIONS=RealitySessions
AZURE_TABLE_EVIDENCE=RealityEvidence
AZURE_TABLE_PROOFS=RealityProofs
AZURE_STORAGE_SAS_TTL_SECONDS=300
```

Connection string authentication takes precedence. Otherwise Azure mode uses
`DefaultAzureCredential` and the Function App Managed Identity.

## Tests and acceptance

- Local and Azure implementations satisfy the same contract.
- Azure clients are fakeable; normal pytest requires no Azure or Azurite.
- Blob hashing is chunked and detects missing, size, type, and hash failures.
- Edge sends correct PUT headers and never includes SAS values in errors.
- Upload failure prevents IngestEvidence.
- Session ETag conflicts and Proof issue retries converge.
- Local StartSession and Phase 6 E2E remain unchanged.
- Azure byte verification removes only the unverified-evidence warning.
- Deployment ZIP includes runtime files and excludes tests, settings, secrets,
  local data, and caches.
- All Phase 0-6 tests continue to pass.

Manual acceptance uses either optional Azurite for basic Blob/Table behavior or
real Azure for Managed Identity, RBAC, and user-delegation SAS.
