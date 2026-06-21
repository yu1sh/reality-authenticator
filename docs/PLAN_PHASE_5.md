# Reality Authenticator Phase 5 Implementation Plan

## Goal

Connect the existing Edge Agent dry-run to the local Cloud APIs and complete
StartSession, evidence generation, ingestion, Proof issuance, verification,
QR, and human-facing verification as one local demonstration.

## Edge and API flow

- `--dry-run --cloud-sync` starts a Cloud Session and uses the returned
  Session ID and button challenge.
- The schema `1.0` Manifest optionally stores the returned public challenge
  fields. Cloud validates them against the saved Session while continuing to
  accept older Manifests without this field.
- Edge sends the Manifest to IngestEvidence, explicitly calls IssueProof,
  validates the returned verification page URL, and calls VerifyProof.
- Successful output includes the Manifest digest, Proof ID, verification page
  URL, QR endpoint, and verification result.

## Authentication

StartSession, IngestEvidence, and IssueProof require `X-Device-Api-Key`.
Missing Cloud configuration fails closed. VerifyProof, public Proof, QR, the
verification page, and CSS remain anonymous. The shared local key is never
stored in evidence or Proof records.

## Demo and tests

`scripts/demo_phase5.sh` starts Azure Functions Core Tools when needed, waits
for the Function host, runs the Edge cloud-sync flow, and leaves a host it
started available until interrupted.

pytest covers HTTP failures, authentication, challenge compatibility, URL
validation, call ordering, failure logging, and a temporary-repository
StartSession-to-verification-page integration flow.

## Deferred scope

Raspberry Pi hardware, real camera and microphone control, Blob Storage,
Key Vault, production Azure deployment, per-device key management, legal
electronic certificates, and proof of AI non-use remain deferred.
