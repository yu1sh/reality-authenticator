from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import get_proof_qr, issue_proof
from reality_cloud.qr import generate_qr_png, verification_page_url
from reality_cloud.storage import LocalJsonRepository


def _issue(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> str:
    session["status"] = "evidence_uploaded"
    repository.save_session(session)
    repository.save_manifest(manifest)
    _, response = issue_proof(
        {"session_id": "session-1"},
        config=config,
        repository=repository,
        clock=lambda: datetime(2026, 6, 9, 1, 0, 4, tzinfo=timezone.utc),
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
    )
    return str(response["proof_id"])


def test_qr_url_and_png_are_deterministic() -> None:
    url = verification_page_url(
        "http://localhost:7071/",
        "RP-proof-1",
    )

    assert url == "http://localhost:7071/verify/RP-proof-1"
    first = generate_qr_png(url)
    second = generate_qr_png(url)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert first == second


def test_qr_requires_existing_proof(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    with pytest.raises(ApiError) as captured:
        get_proof_qr(
            "RP-missing",
            config=config,
            repository=repository,
        )
    assert captured.value.code == "ERR_PROOF_NOT_FOUND"
    assert captured.value.status_code == 404


def test_qr_http_returns_png(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    config: CloudConfig,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUB_SIGNING_SECRET", "test-signing-secret")
    repository = LocalJsonRepository(tmp_path)
    runtime_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=tmp_path,
        stub_signing_secret="test-signing-secret",
    )
    proof_id = _issue(runtime_config, repository, session, manifest)
    request = func.HttpRequest(
        method="GET",
        url=f"http://localhost/api/proofs/{proof_id}/qr",
        headers={},
        params={},
        route_params={"proof_id": proof_id},
        body=b"",
    )

    response = function_app.get_proof_qr_http(request)

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.get_body().startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["Cache-Control"] == "no-store"
