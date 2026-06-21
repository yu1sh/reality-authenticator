# Azure Deployment (Phase 7)

Phase 7-8 deploy the existing Python v2 Function App to Azure Functions Flex
Consumption and replaces local JSON persistence with Azure Table and Blob
Storage, Azure IoT Hub, Application Insights, and Azure Key Vault for Proof
signing. A production custom domain and Microsoft Entra ID remain out of scope.

## Architecture

- Tables: Session state, Evidence ingest result, and Proof index.
- Evidence container: image, audio, and canonical Manifest blobs.
- Proof container: canonical Proof Record blobs.
- Managed Identity: normal Azure authentication path.
- Connection string: local/Azurite or emergency development path only.
- Key Vault: RSA 3072-bit signing key using PS256 and Managed Identity.

Blob containers are private. StartSession creates short-lived, blob-scoped SAS
URLs with create/write permissions so Edge can upload image and audio directly.
IngestEvidence streams both blobs and verifies path, content type, byte length,
and SHA-256 before accepting the Manifest.

## Prerequisites

- Azure CLI 2.60 or newer
- Azure CLI `azure-iot` and `application-insights` extensions. The scripts
  install them when absent.
- Python 3.11 or newer on Linux for the cross-platform deployment build
- An Azure subscription where you can create resources and role assignments
- A globally unique Function App name and Storage account name

Python 3.13 is GA for Azure Functions. Flex Consumption defaults to a 2 GB
instance and no always-ready instances when those options are not supplied.

## Provision

Do not place the secret values below in a committed file or shell history.

```bash
export AZURE_RESOURCE_GROUP=reality-authenticator-dev
export AZURE_LOCATION=japaneast
export AZURE_STORAGE_ACCOUNT_NAME=<globally-unique-lowercase-name>
export AZURE_FUNCTION_APP_NAME=<globally-unique-app-name>
export AZURE_KEY_VAULT_NAME=<globally-unique-vault-name>
export AZURE_IOT_HUB_NAME=<globally-unique-iot-hub-name>
export ADMIN_API_KEY=<administrator-api-key>

./scripts/azure/provision_phase7.sh
./scripts/azure/register_device.sh
```

The script creates the resource group, `Standard_LRS` StorageV2 account,
private containers, Tables, Flex Consumption Function App, RBAC-enabled Key
Vault, RSA 3072 signing key, system-assigned Managed Identity, RBAC assignments,
and application settings. `AzureWebJobsDisableHomepage=true` ensures `/`
is served by the application instead of the Functions default landing page.
The script never deletes resources or old key versions.

Assigned roles:

- Storage Blob Data Contributor
- Storage Blob Delegator
- Storage Table Data Contributor
- Key Vault Crypto User

Role propagation can take several minutes. Retry a smoke test after propagation
instead of adding account keys to the Function App.

## Build and deploy

```bash
./scripts/azure/build_function_zip.sh
./scripts/azure/deploy_phase7.sh
```

The ZIP root contains `function_app.py`, `host.json`, `reality_cloud/`, `web/`,
and `.python_packages/lib/site-packages/`. It excludes tests, local settings,
local evidence, caches, and secrets. Native dependencies are resolved for the
Azure Python 3.13 Linux runtime rather than the host interpreter.

## Edge configuration

`register_device.sh` writes `DEVICE_ID` and
`IOT_HUB_DEVICE_CONNECTION_STRING` to the Git-ignored `edge-agent/.env`. Do not add the
local HTTP `DEVICE_API_KEY` or enable `CLOUD_SYNC_ENABLED` in Azure.

The Azure flow is:

```text
Web StartSession -> IoT Hub C2D -> capture -> image/audio SAS PUT
-> IoT Hub D2C Manifest -> automatic IngestEvidence/IssueProof
-> VerifyProof -> verification page
```

Do not log StartSession's SAS URLs. They are bearer credentials until expiry.

## Smoke test

Run the simulated IoT device acceptance test:

```bash
set -a
source edge-agent/.env
set +a
SMOKE_RUNS=3 ./scripts/azure/smoke_test.sh
```

Track the full completion criteria in
[ACCEPTANCE_STATUS.md](ACCEPTANCE_STATUS.md).

Confirm:

- image/audio/manifest blobs exist below `evidence/<session_id>/`
- the Evidence Table says `evidence_bytes_verified: true`
- the Proof blob and Proof Table row exist
- VerifyProof does not return `EVIDENCE_BYTES_NOT_VERIFIED`
- the Proof uses `PS256` and contains a versioned Key Vault `key_id`
- VerifyProof does not return `STUB_SIGNATURE_NOT_KEY_VAULT`
- `smoke_test.sh` confirms the required AuditLog events and waits for successful
  HTTP request telemetry to appear in Application Insights

## Local and Azurite modes

`USE_AZURE_STORAGE=false` remains the default and requires no Azure SDK
connection or network access. Normal pytest uses fakes for Azure clients.

Azurite is optional. Set `AZURE_STORAGE_CONNECTION_STRING` and
`USE_AZURE_STORAGE=true` for a manual integration run. Managed Identity and
user-delegation SAS behavior must be verified against real Azure.

## Secrets

Never commit Storage connection strings or keys, SAS URLs/tokens,
`AzureWebJobsStorage`, `DEVICE_API_KEY`, `STUB_SIGNING_SECRET`, client secrets,
publish profiles, `local.settings.json`, Azure CLI token caches, deployment
ZIPs, or generated setting dumps.

## References

- [Flex Consumption](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)
- [Supported languages](https://learn.microsoft.com/en-us/azure/azure-functions/supported-languages)
- [ZIP deployment](https://learn.microsoft.com/en-us/azure/azure-functions/deployment-zip-push)
- [User delegation SAS](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-python)
- [Key Vault CryptographyClient](https://learn.microsoft.com/en-us/python/api/azure-keyvault-keys/azure.keyvault.keys.crypto.cryptographyclient)
- [Key Vault RBAC](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide)
