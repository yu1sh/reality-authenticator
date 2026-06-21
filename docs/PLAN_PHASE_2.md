# Reality Authenticator Phase 2 Implementation Plan

## Goal

Add a local Azure Functions Python v2 API foundation for starting proof
sessions and ingesting Phase 1 Evidence Manifests. Persist data as canonical
JSON and keep the storage interface replaceable for later Azure Table and Blob
implementations.

## Scope

- `POST /api/sessions/start`
- `POST /api/evidence/ingest`
- local atomic JSON persistence
- schema version `1.0` Manifest metadata validation
- pytest unit and HTTP-handler tests

GetDeviceCommand, Blob byte verification, IoT Hub, proof issuance, signing,
QR generation, the web UI, and Edge Agent HTTP integration remain deferred.

## API behavior

- StartSession accepts allowlisted devices, generates UUID-based session and
  nonce values, creates a random button and voice challenge, and stores a
  `challenge_issued` Session.
- IngestEvidence validates Session ownership, expiry, capture timestamps,
  button events, sensors, and image/audio metadata.
- Successful ingestion stores the Manifest and changes the Session status to
  `evidence_uploaded`.
- Reposting the same canonical Manifest is idempotent. Posting different
  evidence for the same Session returns `ERR_EVIDENCE_CONFLICT`.
- Validation errors use stable `ERR_*` codes and mark an identifiable Session
  as failed.

## Storage and compatibility

- Data is stored below `LOCAL_DATA_DIR` in `sessions/` and `evidence/`.
- Writes use canonical JSON, a temporary file, and `os.replace`.
- Phase 1 Manifest schema `1.0` is unchanged.
- Both `audio/wav` and the Phase 1 generated `audio/x-wav` are accepted.
- Image and audio hashes are format-checked only; byte verification is Phase 3.

## Acceptance criteria

- Both Functions can be invoked directly with `azure.functions.HttpRequest`.
- Challenge generation, persistence, Manifest validation, error responses,
  failure state updates, and idempotency are covered by pytest.
- Existing Core and Edge tests continue to pass.
