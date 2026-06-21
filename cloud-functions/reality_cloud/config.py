"""Cloud API configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CloudConfig:
    allowed_device_ids: frozenset[str]
    local_data_dir: Path
    device_api_key: str | None = None
    admin_api_key: str | None = None
    allow_local_device_http: bool = True
    time_limit_seconds: int = 10
    grace_seconds: int = 5
    stub_signing_secret: str | None = None
    signature_key_id: str = "local-stub-v1"
    public_web_base_url: str = "http://localhost:7071"
    use_azure_storage: bool = False
    azure_storage_connection_string: str | None = None
    azure_storage_account_name: str | None = None
    azure_blob_container_evidence: str = "reality-evidence"
    azure_blob_container_proofs: str = "reality-proofs"
    azure_table_sessions: str = "RealitySessions"
    azure_table_evidence: str = "RealityEvidence"
    azure_table_proofs: str = "RealityProofs"
    azure_table_devices: str = "RealityDevices"
    azure_table_audit_logs: str = "RealityAuditLogs"
    azure_storage_sas_ttl_seconds: int = 300
    use_azure_key_vault: bool = False
    azure_key_vault_url: str | None = None
    azure_key_vault_key_name: str | None = None
    azure_key_vault_key_version: str | None = None
    azure_client_id: str | None = None
    azure_tenant_id: str | None = None
    azure_client_secret: str | None = None
    use_iot_hub: bool = False
    iot_hub_service_connection_string: str | None = None
    iot_hub_event_hub_name: str = "messages/events"
    iot_hub_consumer_group: str = "$Default"

    @classmethod
    def from_environment(cls) -> "CloudConfig":
        raw_device_ids = os.getenv("ALLOWED_DEVICE_IDS", "raspi-anchor-01")
        device_ids = frozenset(
            value.strip() for value in raw_device_ids.split(",") if value.strip()
        )
        if not device_ids:
            raise ValueError("ALLOWED_DEVICE_IDS must contain at least one device")
        time_limit_seconds = int(os.getenv("TIME_LIMIT_SECONDS", "10"))
        grace_seconds = int(os.getenv("GRACE_SECONDS", "5"))
        if time_limit_seconds < 1:
            raise ValueError("TIME_LIMIT_SECONDS must be positive")
        if grace_seconds < 0:
            raise ValueError("GRACE_SECONDS must not be negative")

        default_data_dir = Path(__file__).resolve().parents[1] / ".local-data"
        use_azure_storage = os.getenv("USE_AZURE_STORAGE", "false").strip().lower()
        if use_azure_storage not in {"true", "false"}:
            raise ValueError("USE_AZURE_STORAGE must be true or false")
        sas_ttl_seconds = int(os.getenv("AZURE_STORAGE_SAS_TTL_SECONDS", "300"))
        if sas_ttl_seconds < 1:
            raise ValueError("AZURE_STORAGE_SAS_TTL_SECONDS must be positive")
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or None
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME") or None
        if use_azure_storage == "true" and not (connection_string or account_name):
            raise ValueError(
                "Azure storage requires AZURE_STORAGE_CONNECTION_STRING "
                "or AZURE_STORAGE_ACCOUNT_NAME"
            )
        use_key_vault = os.getenv("USE_AZURE_KEY_VAULT", "false").strip().lower()
        if use_key_vault not in {"true", "false"}:
            raise ValueError("USE_AZURE_KEY_VAULT must be true or false")
        vault_url = os.getenv("AZURE_KEY_VAULT_URL") or None
        key_name = os.getenv("AZURE_KEY_VAULT_KEY_NAME") or None
        key_version = os.getenv("AZURE_KEY_VAULT_KEY_VERSION") or None
        client_id = os.getenv("AZURE_CLIENT_ID") or None
        tenant_id = os.getenv("AZURE_TENANT_ID") or None
        client_secret = os.getenv("AZURE_CLIENT_SECRET") or None
        client_credentials = (client_id, tenant_id, client_secret)
        if any(client_credentials) and not all(client_credentials):
            raise ValueError(
                "AZURE_CLIENT_ID, AZURE_TENANT_ID, and AZURE_CLIENT_SECRET "
                "must be configured together"
            )
        if use_key_vault == "true" and not (vault_url and key_name):
            raise ValueError(
                "Azure Key Vault requires AZURE_KEY_VAULT_URL "
                "and AZURE_KEY_VAULT_KEY_NAME"
            )
        allow_local_device_http = (
            os.getenv("ALLOW_LOCAL_DEVICE_HTTP", "true").strip().lower()
        )
        if allow_local_device_http not in {"true", "false"}:
            raise ValueError("ALLOW_LOCAL_DEVICE_HTTP must be true or false")
        use_iot_hub = os.getenv("USE_IOT_HUB", "false").strip().lower()
        if use_iot_hub not in {"true", "false"}:
            raise ValueError("USE_IOT_HUB must be true or false")
        iot_service_connection = (
            os.getenv("IOT_HUB_SERVICE_CONNECTION_STRING") or None
        )
        if use_iot_hub == "true" and not iot_service_connection:
            raise ValueError(
                "IoT Hub requires IOT_HUB_SERVICE_CONNECTION_STRING"
            )

        return cls(
            allowed_device_ids=device_ids,
            local_data_dir=Path(os.getenv("LOCAL_DATA_DIR", default_data_dir)),
            device_api_key=os.getenv("DEVICE_API_KEY") or None,
            admin_api_key=os.getenv("ADMIN_API_KEY") or None,
            allow_local_device_http=allow_local_device_http == "true",
            time_limit_seconds=time_limit_seconds,
            grace_seconds=grace_seconds,
            stub_signing_secret=os.getenv("STUB_SIGNING_SECRET") or None,
            signature_key_id=os.getenv("SIGNATURE_KEY_ID", "local-stub-v1"),
            public_web_base_url=os.getenv(
                "PUBLIC_WEB_BASE_URL", "http://localhost:7071"
            ).rstrip("/"),
            use_azure_storage=use_azure_storage == "true",
            azure_storage_connection_string=connection_string,
            azure_storage_account_name=account_name,
            azure_blob_container_evidence=os.getenv(
                "AZURE_BLOB_CONTAINER_EVIDENCE", "reality-evidence"
            ),
            azure_blob_container_proofs=os.getenv(
                "AZURE_BLOB_CONTAINER_PROOFS", "reality-proofs"
            ),
            azure_table_sessions=os.getenv(
                "AZURE_TABLE_SESSIONS", "RealitySessions"
            ),
            azure_table_evidence=os.getenv(
                "AZURE_TABLE_EVIDENCE", "RealityEvidence"
            ),
            azure_table_proofs=os.getenv("AZURE_TABLE_PROOFS", "RealityProofs"),
            azure_table_devices=os.getenv(
                "AZURE_TABLE_DEVICES", "RealityDevices"
            ),
            azure_table_audit_logs=os.getenv(
                "AZURE_TABLE_AUDIT_LOGS", "RealityAuditLogs"
            ),
            azure_storage_sas_ttl_seconds=sas_ttl_seconds,
            use_azure_key_vault=use_key_vault == "true",
            azure_key_vault_url=vault_url,
            azure_key_vault_key_name=key_name,
            azure_key_vault_key_version=key_version,
            azure_client_id=client_id,
            azure_tenant_id=tenant_id,
            azure_client_secret=client_secret,
            use_iot_hub=use_iot_hub == "true",
            iot_hub_service_connection_string=iot_service_connection,
            iot_hub_event_hub_name=os.getenv(
                "IOT_HUB_EVENT_HUB_NAME", "messages/events"
            ),
            iot_hub_consumer_group=os.getenv(
                "IOT_HUB_CONSUMER_GROUP", "$Default"
            ),
        )
