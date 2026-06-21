"""Streaming validation of uploaded evidence blobs."""

from __future__ import annotations

import hashlib
from typing import Mapping


class BlobVerificationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        evidence_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.evidence_name = evidence_name


def _property(properties: object, name: str, default: object = None) -> object:
    if isinstance(properties, Mapping):
        return properties.get(name, default)
    return getattr(properties, name, default)


def verify_blob(container: object, metadata: Mapping[str, object]) -> None:
    blob_path = metadata.get("blob_path")
    expected_hash = metadata.get("sha256")
    expected_size = metadata.get("size_bytes", metadata.get("size"))
    expected_type = metadata.get("content_type")
    if not all(
        (
            isinstance(blob_path, str),
            isinstance(expected_hash, str),
            isinstance(expected_size, int),
            isinstance(expected_type, str),
        )
    ):
        raise BlobVerificationError("ERR_INVALID_MANIFEST", "invalid file metadata")

    blob = container.get_blob_client(blob_path)
    try:
        properties = blob.get_blob_properties()
    except Exception as error:
        if error.__class__.__name__ == "ResourceNotFoundError":
            raise BlobVerificationError(
                "ERR_FILE_MISSING", "evidence blob was not found"
            ) from error
        raise

    actual_size = _property(properties, "size")
    if actual_size != expected_size:
        raise BlobVerificationError(
            "ERR_HASH_MISMATCH", "evidence blob size does not match"
        )
    content_settings = _property(properties, "content_settings", {})
    actual_type = _property(content_settings, "content_type")
    wav_types = {"audio/wav", "audio/x-wav"}
    if actual_type != expected_type and not {
        str(actual_type),
        str(expected_type),
    } <= wav_types:
        raise BlobVerificationError(
            "ERR_HASH_MISMATCH", "evidence blob content type does not match"
        )

    digest = hashlib.sha256()
    downloader = blob.download_blob()
    for chunk in downloader.chunks():
        digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        raise BlobVerificationError(
            "ERR_HASH_MISMATCH", "evidence blob hash does not match"
        )


def verify_manifest_blobs(
    evidence_container: object, manifest: Mapping[str, object]
) -> None:
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise BlobVerificationError("ERR_INVALID_MANIFEST", "files are required")
    for name in ("image", "audio"):
        metadata = files.get(name)
        if not isinstance(metadata, Mapping):
            raise BlobVerificationError(
                "ERR_FILE_MISSING", f"{name} metadata is required"
            )
        try:
            verify_blob(evidence_container, metadata)
        except BlobVerificationError as error:
            error.evidence_name = name
            raise
