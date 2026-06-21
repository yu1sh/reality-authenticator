# Reality Authenticator Phase 4 Implementation Plan

## Goal

Provide a public, local verification experience from the existing Azure
Functions application: a server-rendered verification page, a public Proof
projection, and a QR PNG containing the page URL.

## Routes

- `GET /verify/{proof_id}` renders accepted, invalid, rejected, or not-found
  states without client-side JavaScript.
- `GET /api/proofs/{proof_id}` returns only public Proof fields.
- `GET /api/proofs/{proof_id}/qr` returns a PNG QR code for the verification
  page.
- Existing API routes retain their `/api/...` paths after the Function host
  route prefix is removed.

## Privacy and security

The public projection excludes Session and Evidence IDs, challenge nonce and
voice code, key identifiers, storage paths, evidence media, and internal
errors. Dynamic HTML values are escaped. Responses use no-store caching and
restrict content with CSP and related security headers.

The page states clearly that STUB-HS256 is not Key Vault signing, evidence file
bytes are not verified, and the page is not a legal certificate, identity
check, or proof of AI non-use.

## Deferred scope

Static Web Apps, Front Door, custom domains, Key Vault, Blob delivery, login,
production deployment, legal certificates, and complete proof of AI non-use
remain out of scope.
