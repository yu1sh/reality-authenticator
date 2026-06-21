from __future__ import annotations

import inspect
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import azure.functions as func
import pytest

import function_app
from reality_cloud.config import CloudConfig
from reality_cloud.handlers import get_verification_page, issue_proof
from reality_cloud.presentation import render_verification_page
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


def test_accepted_page_displays_public_integrity_values(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issue(config, repository, session, manifest)

    status, html = get_verification_page(
        proof_id,
        config=config,
        repository=repository,
    )

    proof = repository.load_proof(proof_id)
    assert status == 200
    assert "WARNING" in html
    assert proof_id in html
    assert proof["device_id"] in html
    assert proof["captured_at"] in html
    assert proof["manifest_hash"] in html
    assert proof["record_hash"] in html
    assert proof["signature"] in html
    assert proof["key_id"] in html
    assert proof["signed_at"] in html
    assert "ローカル開発用署名" in html
    assert "Azure Key Vault 署名ではありません" in html
    assert "法的な電子証明書" in html
    assert manifest["files"]["image"]["sha256"] in html
    assert manifest["files"]["audio"]["sha256"] in html
    assert f"/api/proofs/{proof_id}/qr" in html


def test_invalid_page_is_returned_for_tampered_proof(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issue(config, repository, session, manifest)
    proof = repository.load_proof(proof_id)
    proof["device_id"] = "other-device"
    repository.save_proof(proof)

    status, html = get_verification_page(
        proof_id,
        config=config,
        repository=repository,
    )

    assert status == 200
    assert "INVALID" in html
    assert "不一致" in html


def test_rejected_page_is_returned_when_verification_cannot_run(
    config: CloudConfig,
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    proof_id = _issue(config, repository, session, manifest)
    no_secret_config = CloudConfig(
        allowed_device_ids=config.allowed_device_ids,
        local_data_dir=config.local_data_dir,
        public_web_base_url=config.public_web_base_url,
    )

    status, html = get_verification_page(
        proof_id,
        config=no_secret_config,
        repository=repository,
    )

    assert status == 503
    assert "REJECTED" in html


def test_not_found_page_uses_404(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    status, html = get_verification_page(
        "RP-missing",
        config=config,
        repository=repository,
    )

    assert status == 404
    assert "NOT FOUND" in html
    assert "QR を利用できません" in html


def test_malformed_stored_proof_is_rejected(
    config: CloudConfig,
    repository: LocalJsonRepository,
) -> None:
    proof_path = repository.root / "proofs" / "RP-broken.json"
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text("{broken", encoding="utf-8")

    status, html = get_verification_page(
        "RP-broken",
        config=config,
        repository=repository,
    )

    assert status == 503
    assert "REJECTED" in html


def test_html_escapes_dynamic_values() -> None:
    html = render_verification_page(
        proof_id="<script>alert(1)</script>",
        state="invalid",
        proof={
            "device_id": '"><img src=x onerror=alert(1)>',
            "challenge": {},
        },
        verification={"checks": {"<script>": False}, "warnings": ["<b>warning</b>"]},
    )

    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;warning&lt;/b&gt;" in html


def test_ps256_page_describes_key_vault_signature() -> None:
    html = render_verification_page(
        proof_id="RP-1",
        state="accepted",
        proof={
            "signature_algorithm": "PS256",
            "key_id": "https://vault.vault.azure.net/keys/key/version",
            "signed_at": "2026-06-15T00:00:00.000+00:00",
            "challenge": {},
        },
        verification={"checks": {}, "warnings": []},
    )

    assert "Azure Key Vault の管理鍵" in html
    assert "ローカル開発用署名" not in html


def test_verification_page_http_sets_security_headers(
    tmp_path: Path,
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
        url=f"http://localhost/verify/{proof_id}",
        headers={},
        params={},
        route_params={"proof_id": proof_id},
        body=b"",
    )

    response = function_app.verification_page_http(request)

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_css_http_is_served_without_external_dependencies() -> None:
    request = func.HttpRequest(
        method="GET",
        url="http://localhost/assets/verify.css",
        headers={},
        params={},
        route_params={},
        body=b"",
    )

    response = function_app.verification_css_http(request)

    assert response.status_code == 200
    assert response.mimetype == "text/css"
    assert b".status-accepted" in response.get_body()


def test_function_routes_keep_api_prefix_and_add_page_routes() -> None:
    routes = set()
    for function in function_app.app.get_functions():
        for raw_binding in function.get_raw_bindings():
            binding = json.loads(raw_binding)
            if binding.get("type") == "httpTrigger":
                routes.add((binding["route"], tuple(binding["methods"])))

    assert ("api/sessions/start", ("POST",)) in routes
    assert ("api/devices", ("GET",)) in routes
    assert ("api/sessions/{session_id}", ("GET",)) in routes
    assert ("api/admin/proofs/{proof_id}", ("GET",)) in routes
    assert ("api/evidence/ingest", ("POST",)) in routes
    assert ("api/proofs/issue", ("POST",)) in routes
    assert ("api/proofs/{proof_id}/verify", ("POST",)) in routes
    assert ("api/proofs/{proof_id}", ("GET",)) in routes
    assert ("api/proofs/{proof_id}/qr", ("GET",)) in routes
    assert ("verify/{proof_id}", ("GET",)) in routes
    assert ("/", ("GET",)) in routes
    assert ("start", ("GET",)) in routes
    assert ("session/{session_id}", ("GET",)) in routes
    assert ("proof/{proof_id}", ("GET",)) in routes
    assert ("assets/app.css", ("GET",)) in routes
    assert ("assets/app.js", ("GET",)) in routes
    assert ("assets/verify.css", ("GET",)) in routes

    host = json.loads(
        (Path(__file__).resolve().parents[1] / "host.json").read_text()
    )
    assert host["extensions"]["http"]["routePrefix"] == ""


def test_http_entry_points_only_accept_the_request_binding() -> None:
    handlers = {
        name: builder._function.get_user_function()
        for name, builder in inspect.getmembers(function_app)
        if name.endswith("_http")
        and hasattr(builder, "_function")
    }

    assert handlers
    for name, handler in handlers.items():
        assert list(inspect.signature(handler).parameters) == ["req"], name


def test_root_page_and_default_homepage_settings_are_deployable() -> None:
    project_root = Path(__file__).resolve().parents[1]
    settings = json.loads(
        (project_root / "local.settings.json.example").read_text()
    )
    provision = (
        project_root.parent / "scripts" / "azure" / "provision_phase7.sh"
    ).read_text()
    register = (
        project_root.parent / "scripts" / "azure" / "register_device.sh"
    ).read_text()

    assert settings["Values"]["AzureWebJobsDisableHomepage"] == "true"
    assert "AzureWebJobsDisableHomepage=true" in provision
    assert "application-insights" in provision
    assert 'OUTPUT_ENV_FILE="${OUTPUT_ENV_FILE:-edge-agent/.env}"' in register
    assert "iot_hub_device_id=" in register

    smoke = (
        project_root.parent / "scripts" / "azure" / "smoke_test.sh"
    ).read_text()
    assert "proof_verified" in smoke
    assert "az monitor app-insights query" in smoke
