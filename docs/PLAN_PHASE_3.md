# Reality Authenticator Phase 3 Implementation Plan

## Goal

Issue a locally verifiable Proof Record from accepted evidence using a clearly
labelled HMAC-SHA256 signing stub. Store Proof Records as canonical JSON and
expose explicit issue and verification APIs.

## Proof integrity

The Cloud service computes `manifest_hash` from the stored canonical Manifest.
It then constructs an explicit unsigned Proof payload containing identity,
capture, challenge, Manifest hash, and creation time fields. `record_hash` is
SHA-256 over that canonical payload.

The stub signs the binary Record Hash with HMAC-SHA256 and emits unpadded
Base64URL. `record_hash`, signature metadata, and verification URL are outside
the Record Hash boundary. The algorithm is labelled `STUB-HS256`; it is not an
electronic signature or a Key Vault substitute.

## APIs

- `POST /api/proofs/issue` accepts a Session ID and issues one Proof for an
  `evidence_uploaded` Session. Repeated requests return the existing Proof.
- `POST /api/proofs/{proof_id}/verify` recalculates Manifest Hash, Record Hash,
  and the stub signature. Stored-data tampering returns HTTP 200 with
  `valid: false`; a missing Proof returns 404.

## Storage

Proofs are stored at `.local-data/proofs/<proof_id>.json`. Successful issue
updates the Session with `proof_id` and status `proof_issued`.

## Deferred scope

Azure Key Vault, Blob Storage byte verification, QR and human-facing
verification pages, Web UI, Azure deployment, legal certificates, and complete
proof of AI non-use remain out of scope.
