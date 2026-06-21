# Reality Authenticator Phase 8 Implementation Plan

Historical note: this document describes the Phase 8 signing slice. The final
MVP scope is defined by `docs/spec.md` v1.2 and includes additional IoT Hub,
Web UI, Device, AuditLog, and acceptance work.

## Goal

Phase 8 replaces the Proof signing stub with optional Azure Key Vault PS256
signing while retaining schema 1.0 `STUB-HS256` verification compatibility.
New Proof Records use schema 1.2 in both local and Azure modes. The signed
payload includes the public-key metadata; schema 1.0 and 1.1 remain readable
for verification compatibility.

Azure mode uses an RSA 3072-bit software-protected key. When
`USE_AZURE_KEY_VAULT=true`, Key Vault signing is mandatory and failures never
fall back to the local secret.

## Proof integrity

Schema 1.1 includes `signature_algorithm`, versioned `key_id`, and `signed_at`
inside the canonical unsigned payload. `record_hash` is SHA-256 over that
payload. `record_hash`, `signature`, and `verification_url` remain outside the
hash boundary.

The signing sequence is:

```text
resolve versioned key ID
-> reserve proof ID, timestamps, algorithm, and key ID in Session
-> canonicalize unsigned Proof
-> SHA-256 record hash
-> Key Vault sign(PS256, digest bytes)
-> unpadded Base64URL signature
-> save Proof and finalize Session
```

Reservation fields are reused after retries. PS256 signatures are
non-deterministic, so idempotency compares the record hash, key ID, algorithm,
and Proof identity rather than signature bytes.

## Signing abstraction

`Signer` resolves a `SigningProfile` and signs a 32-byte digest. `Verifier`
verifies a digest, signature, algorithm, and versioned key ID.

- `LocalStubSigner` and `LocalStubVerifier` preserve local development.
- `AzureKeyVaultSigner` resolves the configured key version and calls
  `CryptographyClient.sign`.
- `AzureKeyVaultVerifier` validates the key ID origin/name/version and calls
  `CryptographyClient.verify`.
- Azure SDK errors are converted to stable signing-unavailable errors without
  exposing credentials or service response details.

VerifyProof selects legacy stub verification for `STUB-HS256` and Key Vault
verification for `PS256`. Key Vault unavailability returns 503; a validly
completed verification with a bad signature returns HTTP 200 and `valid:false`.

## Azure deployment

Configuration:

```env
USE_AZURE_KEY_VAULT=false
AZURE_KEY_VAULT_URL=
AZURE_KEY_VAULT_KEY_NAME=reality-proof-signing
AZURE_KEY_VAULT_KEY_VERSION=
AZURE_CLIENT_ID=
AZURE_TENANT_ID=
AZURE_CLIENT_SECRET=
```

Managed Identity is the production authentication path. Service principal
variables must be provided as a complete set and are intended only for local
or CI integration. An omitted key version resolves the latest version, but the
resolved versioned key ID is always stored in the Proof.

Provisioning creates an RBAC-enabled Key Vault with purge protection, creates
an RSA 3072 sign/verify key, grants the Function identity `Key Vault Crypto
User`, and enables Key Vault signing in Function settings. Old key versions
must remain available to verify historical Proofs.

## Tests and acceptance

- Exact schema 1.0 and 1.1 hash boundaries are tested.
- Algorithm, key ID, and signed timestamp mutations change the record hash.
- Signature and verification URL mutations do not change the record hash.
- Key version resolution, PS256 digest signing, verification, invalid key IDs,
  and sanitized failures use fake clients.
- Key Vault mode is fail-closed and never invokes the stub.
- Legacy schema 1.0 Proofs remain verifiable.
- Public JSON and HTML show key ID and signed timestamp.
- Stub warnings appear only for stub Proofs.
- Real Key Vault sign/verify is opt-in through
  `RUN_AZURE_KEY_VAULT_INTEGRATION=1`.
- All dry-run, real-device, local E2E, Azure Storage, Proof, QR, and web tests
  pass without Azure network access.

## Deferred scope

Production domains, strict user authentication, legal electronic certificates,
proof of AI non-use, biometrics, offline verification, Managed HSM, and
automatic key rotation remain out of scope.
