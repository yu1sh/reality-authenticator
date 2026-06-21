"""End-to-end dry-run synchronization with the Cloud API."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .cloud_client import CloudClient, CloudClientError
from .blob_upload import BlobUploadError, upload_evidence_files
from .dry_run import InputFunction, run_dry_run


class CloudSyncError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CloudSyncResult:
    manifest_path: Path
    proof_id: str
    verification_url: str
    qr_url: str
    verification: dict[str, object]


CaptureFunction = Callable[
    [str, dict[str, object], str],
    Path,
]
UploadFunction = Callable[..., None]


def _validate_verification_url(
    verification_url: str,
    *,
    verify_base_url: str,
    proof_id: str,
) -> None:
    try:
        actual = urlsplit(verification_url)
        expected = urlsplit(verify_base_url.rstrip("/"))
        actual_origin = (actual.scheme, actual.hostname, actual.port)
        expected_origin = (expected.scheme, expected.hostname, expected.port)
    except ValueError as error:
        raise CloudSyncError(
            "ERR_VERIFICATION_URL",
            "verification_url is not a valid URL",
        ) from error
    if (
        actual_origin != expected_origin
        or actual.path != f"/verify/{proof_id}"
        or actual.query
        or actual.fragment
    ):
        raise CloudSyncError(
            "ERR_VERIFICATION_URL",
            "verification_url does not match VERIFY_BASE_URL and proof_id",
        )


def _append_failure(manifest_path: Path, code: str) -> None:
    with (manifest_path.parent / "edge.log").open("a", encoding="utf-8") as log:
        log.write("cloud_sync=failed\n")
        log.write(f"failure_code={code}\n")


def run_cloud_sync(
    *,
    client: CloudClient,
    output_dir: Path,
    fixtures_dir: Path,
    device_id: str,
    verify_base_url: str,
    interactive: bool = False,
    edge_version: str = "0.1.0",
    input_func: InputFunction = input,
    capture: CaptureFunction | None = None,
    uploader: UploadFunction = upload_evidence_files,
) -> CloudSyncResult:
    session = client.start_session(device_id)
    session_id = str(session["session_id"])
    challenge = dict(session["challenge"])
    if capture is None:
        manifest_path = run_dry_run(
            output_dir=output_dir,
            fixtures_dir=fixtures_dir,
            device_id=device_id,
            session_id=session_id,
            button_count=int(challenge["button_count"]),
            interactive=interactive,
            edge_version=edge_version,
            challenge=challenge,
            input_func=input_func,
        )
    else:
        manifest_path = capture(session_id, challenge, str(session["expires_at"]))

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise CloudSyncError(
                "ERR_INVALID_MANIFEST",
                "generated Manifest is not a JSON object",
            )
        upload = session.get("upload")
        if upload is not None:
            if not isinstance(upload, dict):
                raise CloudSyncError(
                    "ERR_UPLOAD_REQUIRED", "Cloud upload configuration is invalid"
                )
            uploader(upload=upload, manifest_path=manifest_path)
        client.ingest_evidence(manifest)
        issue = client.issue_proof(session_id)
        proof_id = str(issue["proof_id"])
        verification_url = str(issue["verification_url"])
        _validate_verification_url(
            verification_url,
            verify_base_url=verify_base_url,
            proof_id=proof_id,
        )
        verification = client.verify_proof(proof_id)
    except CloudClientError as error:
        _append_failure(manifest_path, error.code)
        raise
    except BlobUploadError as error:
        _append_failure(manifest_path, error.code)
        raise CloudSyncError(error.code, error.message) from error
    except CloudSyncError as error:
        _append_failure(manifest_path, error.code)
        raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _append_failure(manifest_path, "ERR_INVALID_MANIFEST")
        raise CloudSyncError(
            "ERR_INVALID_MANIFEST",
            "generated Manifest could not be read",
        ) from error

    return CloudSyncResult(
        manifest_path=manifest_path,
        proof_id=proof_id,
        verification_url=verification_url,
        qr_url=f"{client.api_base_url}/proofs/{proof_id}/qr",
        verification=verification,
    )
