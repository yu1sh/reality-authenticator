"""Direct evidence upload to short-lived Azure Blob SAS URLs."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BlobUploadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


OpenFunction = Callable[..., Any]


def upload_evidence_files(
    *,
    upload: Mapping[str, object],
    manifest_path: Path,
    opener: OpenFunction = urlopen,
    timeout_seconds: float = 5.0,
) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise BlobUploadError(
            "ERR_INVALID_MANIFEST", "Manifest could not be used for upload"
        ) from error
    if not isinstance(files, dict):
        raise BlobUploadError("ERR_INVALID_MANIFEST", "Manifest files are invalid")

    for name, filename in (("image", "image.jpg"), ("audio", "audio.wav")):
        target = upload.get(name)
        metadata = files.get(name)
        if not isinstance(target, Mapping) or not isinstance(metadata, Mapping):
            raise BlobUploadError(
                "ERR_UPLOAD_REQUIRED", f"{name} upload target is missing"
            )
        url = target.get("url")
        content_type = target.get("content_type")
        manifest_content_type = metadata.get("content_type")
        content_types_match = content_type == manifest_content_type or {
            str(content_type),
            str(manifest_content_type),
        } <= {"audio/wav", "audio/x-wav"}
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not content_types_match
            or target.get("blob_path") != metadata.get("blob_path")
        ):
            raise BlobUploadError(
                "ERR_UPLOAD_REQUIRED", f"{name} upload target is invalid"
            )
        try:
            payload = (manifest_path.parent / filename).read_bytes()
        except OSError as error:
            raise BlobUploadError(
                "ERR_UPLOAD_FAILED", f"{name} evidence file could not be read"
            ) from error
        request = Request(
            url,
            data=payload,
            headers={
                "Content-Type": str(content_type),
                "x-ms-blob-type": "BlockBlob",
            },
            method="PUT",
        )
        try:
            response = opener(request, timeout=timeout_seconds)
            close = getattr(response, "close", None)
            if close is not None:
                close()
        except HTTPError as error:
            raise BlobUploadError(
                "ERR_UPLOAD_FAILED", f"{name} upload failed"
            ) from error
        except (TimeoutError, socket.timeout, URLError, OSError) as error:
            raise BlobUploadError(
                "ERR_UPLOAD_FAILED", f"{name} upload failed"
            ) from error
