# Reality Authenticator Acceptance Status

Updated: 2026-06-16

This file tracks the concrete evidence for the MVP completion criteria in
`docs/spec.md` section 22.4. A criterion is complete only when the listed
evidence has been produced in the target environment.

Latest local verification on 2026-06-16:

- Full pytest: `236 passed, 1 skipped` on both `/tmp/reality-py313-venv` and
  `.venv`.
- Shell syntax and Python compile checks passed.
- Deployment ZIP rebuilt at
  `cloud-functions/.deployment/reality-authenticator-functions.zip`; required
  Function/web entries are present, with no incompatible platform or Python ABI
  artifacts detected.
- Functions Core Tools E2E issued Proof
  `RP-776c6501-2226-47e6-ab44-ac497a8b474c` for Session
  `72992431-59f2-4a1a-8f22-c76454195052`. Local verification status was
  `WARNING`, as required for stub signing and non-restreamed local media.
- Public Proof projection had schema `1.2`, no private identifiers or Blob
  paths, QR returned PNG, and AuditLog contained the required local events and
  status transitions.

## Current Status

| ID | Criterion | Current evidence | Status |
|---|---|---|---|
| AC-01 | Web 画面から証明開始できる。 | Local Functions host served `/`, `/start`, and `POST /api/sessions/start`; pytest covers the routes and admin auth. | Locally verified |
| AC-02 | Raspberry Pi が Azure IoT Hub 経由でチャレンジを取得できる。 | Edge implements `azure-iot-device` C2D listener, command validation, heartbeat, duplicate store, and tests. | Requires Azure + Pi |
| AC-03 | 物理ボタン操作が記録される。 | GPIO capture and debounce tests exist; real hardware access is not present in this workspace. | Requires Pi |
| AC-04 | センサ値が 2 種類以上記録される。 | Grove serial reader and Manifest validation require at least two numeric sensors; tests cover valid and invalid sensor data. | Code verified |
| AC-05 | 画像と音声が保存される。 | Dry-run and local real-capture code write `image.jpg` and `audio.wav`; Blob upload code and Azure verification are tested with fakes. | Requires Azure + Pi for final |
| AC-06 | 画像と音声の SHA-256 と Manifest Hash が Proof に含まれる。 | Local E2E produced public projection with image/audio SHA-256 and Proof `manifest_hash`; tests cover projection privacy. | Locally verified |
| AC-07 | Record Hash が作成される。 | Proof tests verify schema 1.2 unsigned payload and `record_hash`; local E2E returned a record hash. | Locally verified |
| AC-08 | Azure dev では Key Vault PS256 で署名できる。 | Key Vault signer/verifier and deployment scripts are implemented; opt-in integration test is present. | Requires Azure login |
| AC-09 | QR コードから検証ページを開ける。 | Local E2E saved and fetched PNG QR; verification page rendered from Proof ID. | Locally verified |
| AC-10 | 検証ページに `VALID` と証明内容が表示される。 | Local mode correctly shows `WARNING`; `VALID` requires Azure PS256 and Blob byte re-verification. | Requires Azure |
| AC-11 | AuditLog と Application Insights に主要イベントが記録される。 | AuditLog is locally verified; `smoke_test.sh` checks AuditLog and App Insights requests in Azure. | Requires Azure |
| AC-12 | 指定 Raspberry Pi 実機で 30 秒以内の正常実行を 3 回連続で成功できる。 | `smoke_test.sh` defaults to 3 runs and 30 seconds; no Pi hardware is exposed here. | Requires Azure + Pi |

## Final Acceptance Command

After provisioning Azure and configuring the Raspberry Pi:

```bash
set -a
source edge-agent/.env
set +a
SMOKE_RUNS=3 SMOKE_TIMEOUT_SECONDS=30 ./scripts/azure/smoke_test.sh
```

The command must finish with:

```text
Acceptance complete: 3 consecutive runs, AuditLog complete, Application Insights requests=<n>
```

Each run must print a `VALID` Proof and complete within 30 seconds.

## Current External Blockers

- `az account show` currently requires `az login`.
- This workspace does not expose Raspberry Pi hardware devices such as
  `/dev/gpiochip*`, `/dev/video*`, or `/dev/snd`.
