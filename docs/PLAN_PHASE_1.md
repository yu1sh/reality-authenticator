# Reality Authenticator Phase 0-1 Implementation Plan

## Goal

Provide a local, hardware-independent Edge Agent dry-run that creates a
deterministic Evidence Manifest with image, audio, sensor, and button evidence.
All evidence is protected with SHA-256, and JSON used for hashing is serialized
canonically.

## Phase 0

- Keep the authoritative specification at `docs/spec.md`.
- Add repository documentation, ignore rules, example environment settings,
  and Python package metadata.
- Place hash and canonical JSON behavior in the reusable `reality-core`
  package so future cloud code uses the same implementation.
- Support Python 3.11 and newer.

## Phase 1

1. Implement chunked SHA-256 hashing for bytes and files.
2. Implement UTF-8 canonical JSON with sorted keys, compact separators, and
   rejection of NaN and infinity.
3. Build schema version `1.0` Evidence Manifests.
4. Generate a dry-run bundle from stable JPEG and WAV fixtures.
5. Support unattended automatic button events and optional interactive Enter
   key capture.
6. Write `image.jpg`, `audio.wav`, `manifest.json`, `manifest.sha256`, and
   `edge.log` below a session directory.
7. Verify unit and CLI behavior with pytest.

## Public interfaces

- `canonical_json_bytes(value) -> bytes`
- `canonical_json_text(value) -> str`
- `sha256_bytes(data) -> str`
- `sha256_file(path) -> str`
- `build_evidence_manifest(...) -> dict[str, object]`
- `write_evidence_bundle(...) -> Path`

## Deferred scope

Azure Functions, Blob Storage upload, IoT Hub, session APIs, Proof Records,
signing, QR codes, web UI, GPIO, and real camera/microphone/sensor access are
deferred to Phase 2 and later.

## Acceptance criteria

- `python -m reality_edge.main --dry-run` succeeds without Azure or GPIO.
- A schema version `1.0` manifest and all five bundle files are generated.
- Recomputed image, audio, and manifest SHA-256 values match recorded values.
- Canonical JSON does not depend on input key order or whitespace.
- All pytest tests pass.
- Generated evidence and secrets are excluded from Git.
