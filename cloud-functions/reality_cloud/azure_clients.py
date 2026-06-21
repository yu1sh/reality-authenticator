"""Lazy Azure SDK client construction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .storage_azure import AzureStorageRepository


def create_azure_repository(config: object) -> AzureStorageRepository:
    try:
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import (
            BlobSasPermissions,
            BlobServiceClient,
            generate_blob_sas,
        )
    except ImportError as error:
        raise RuntimeError("Azure Storage dependencies are not installed") from error

    connection_string = getattr(config, "azure_storage_connection_string")
    account_name = getattr(config, "azure_storage_account_name")
    credential = None
    if connection_string:
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        table_service = TableServiceClient.from_connection_string(connection_string)
        parts = dict(
            part.split("=", 1)
            for part in connection_string.split(";")
            if "=" in part
        )
        account_name = parts.get("AccountName") or blob_service.account_name
        account_key = parts.get("AccountKey")
    else:
        credential = DefaultAzureCredential()
        blob_service = BlobServiceClient(
            f"https://{account_name}.blob.core.windows.net", credential=credential
        )
        table_service = TableServiceClient(
            f"https://{account_name}.table.core.windows.net", credential=credential
        )
        account_key = None

    evidence_container_name = getattr(config, "azure_blob_container_evidence")
    proof_container_name = getattr(config, "azure_blob_container_proofs")
    evidence_container = blob_service.get_container_client(evidence_container_name)
    proof_container = blob_service.get_container_client(proof_container_name)

    def sas_factory(path: str, content_type: str, expires_at: str) -> str:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        start = datetime.now(timezone.utc) - timedelta(minutes=5)
        delegation_key = None
        if account_key is None:
            delegation_key = blob_service.get_user_delegation_key(start, expiry)
        token = generate_blob_sas(
            account_name=account_name,
            container_name=evidence_container_name,
            blob_name=path,
            account_key=account_key,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(create=True, write=True),
            expiry=expiry,
            start=start,
            protocol="https",
            content_type=content_type,
        )
        return f"{evidence_container.get_blob_client(path).url}?{token}"

    return AzureStorageRepository(
        sessions_table=table_service.get_table_client(
            getattr(config, "azure_table_sessions")
        ),
        evidence_table=table_service.get_table_client(
            getattr(config, "azure_table_evidence")
        ),
        proofs_table=table_service.get_table_client(
            getattr(config, "azure_table_proofs")
        ),
        devices_table=table_service.get_table_client(
            getattr(config, "azure_table_devices")
        ),
        audit_logs_table=table_service.get_table_client(
            getattr(config, "azure_table_audit_logs")
        ),
        evidence_container=evidence_container,
        proofs_container=proof_container,
        sas_factory=sas_factory,
    )
