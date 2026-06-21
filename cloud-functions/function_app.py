"""Azure Functions Python v2 entry points."""

from __future__ import annotations

import json
import logging
import secrets
from uuid import uuid4

import azure.functions as func

from reality_cloud.audit import write_audit_log
from reality_cloud.auth import require_admin_api_key, require_device_api_key
from reality_cloud.config import CloudConfig
from reality_cloud.errors import ApiError
from reality_cloud.handlers import (
    get_proof_qr,
    get_admin_proof,
    get_session,
    get_public_proof,
    get_verification_page,
    ingest_evidence,
    issue_proof,
    list_devices,
    start_session,
    verify_proof,
)
from reality_cloud.presentation import load_verification_css
from reality_cloud.storage import create_storage
from reality_cloud.storage_contract import StorageRepository
from reality_cloud.iot import parse_telemetry
from reality_cloud.telemetry import process_telemetry
from reality_cloud.web_app import load_app_asset, render_app_page

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _dependencies() -> tuple[CloudConfig, StorageRepository]:
    config = CloudConfig.from_environment()
    return config, create_storage(config)


def _json_response(payload: dict[str, object], status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        status_code=status_code,
        mimetype="application/json",
        charset="utf-8",
    )


def _request_json(req: func.HttpRequest) -> object:
    try:
        return req.get_json()
    except ValueError as error:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be valid JSON", 400) from error


def _handle(operation) -> func.HttpResponse:
    try:
        status_code, payload = operation()
        return _json_response(payload, status_code)
    except ApiError as error:
        return _json_response(error.to_dict(), error.status_code)
    except Exception:
        logging.exception("Unhandled Reality Authenticator API error")
        error = ApiError("ERR_INTERNAL", "internal server error", 500)
        return _json_response(error.to_dict(), error.status_code)


def _authenticate(req: func.HttpRequest, config: CloudConfig) -> None:
    if not config.allow_local_device_http:
        raise ApiError(
            "ERR_ENDPOINT_DISABLED",
            "local device HTTP endpoints are disabled",
            404,
        )
    require_device_api_key(req.headers, config.device_api_key)


def _authenticate_admin(req: func.HttpRequest, config: CloudConfig) -> None:
    require_admin_api_key(req.headers, config.admin_api_key)


def _authenticate_start(req: func.HttpRequest, config: CloudConfig) -> None:
    if req.headers.get("X-Admin-Api-Key"):
        _authenticate_admin(req, config)
        return
    _authenticate(req, config)


def _security_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self'; style-src 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


def _app_page(page: str, resource_id: str = "") -> func.HttpResponse:
    return func.HttpResponse(
        body=render_app_page(page, resource_id),
        status_code=200,
        mimetype="text/html",
        charset="utf-8",
        headers=_security_headers(),
    )


@app.route(route="/", methods=["GET"])
def home_page_http(req: func.HttpRequest) -> func.HttpResponse:
    return _app_page("home")


@app.route(route="start", methods=["GET"])
def start_page_http(req: func.HttpRequest) -> func.HttpResponse:
    return _app_page("start")


@app.route(route="session/{session_id}", methods=["GET"])
def session_page_http(req: func.HttpRequest) -> func.HttpResponse:
    return _app_page("session", req.route_params.get("session_id", ""))


@app.route(route="proof/{proof_id}", methods=["GET"])
def proof_page_http(req: func.HttpRequest) -> func.HttpResponse:
    return _app_page("proof", req.route_params.get("proof_id", ""))


@app.route(route="assets/app.css", methods=["GET"])
def app_css_http(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        body=load_app_asset("app.css"),
        status_code=200,
        mimetype="text/css",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.route(route="assets/app.js", methods=["GET"])
def app_js_http(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        body=load_app_asset("app.js"),
        status_code=200,
        mimetype="text/javascript",
        charset="utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.route(route="api/sessions/start", methods=["POST"])
def start_session_http(req: func.HttpRequest) -> func.HttpResponse:
    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate_start(req, config)
        return start_session(
            _request_json(req),
            config=config,
            repository=repository,
            uuid_factory=uuid4,
            randbelow=secrets.randbelow,
        )

    return _handle(operation)


@app.route(route="api/evidence/ingest", methods=["POST"])
def ingest_evidence_http(req: func.HttpRequest) -> func.HttpResponse:
    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate(req, config)
        return ingest_evidence(_request_json(req), repository=repository)

    return _handle(operation)


@app.route(route="api/proofs/issue", methods=["POST"])
def issue_proof_http(req: func.HttpRequest) -> func.HttpResponse:
    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate(req, config)
        return issue_proof(
            _request_json(req),
            config=config,
            repository=repository,
            uuid_factory=uuid4,
        )

    return _handle(operation)


@app.route(route="api/devices", methods=["GET"])
def list_devices_http(req: func.HttpRequest) -> func.HttpResponse:
    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate_admin(req, config)
        return list_devices(config=config, repository=repository)

    return _handle(operation)


@app.route(route="api/sessions/{session_id}", methods=["GET"])
def get_session_http(req: func.HttpRequest) -> func.HttpResponse:
    session_id = req.route_params.get("session_id", "")

    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate_admin(req, config)
        return get_session(session_id, repository=repository)

    return _handle(operation)


@app.route(route="api/admin/proofs/{proof_id}", methods=["GET"])
def get_admin_proof_http(req: func.HttpRequest) -> func.HttpResponse:
    proof_id = req.route_params.get("proof_id", "")

    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        _authenticate_admin(req, config)
        return get_admin_proof(proof_id, repository=repository)

    return _handle(operation)


@app.route(route="api/proofs/{proof_id}/verify", methods=["POST"])
def verify_proof_http(req: func.HttpRequest) -> func.HttpResponse:
    proof_id = req.route_params.get("proof_id", "")

    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        return verify_proof(
            proof_id,
            config=config,
            repository=repository,
        )

    return _handle(operation)


@app.route(route="api/proofs/{proof_id}", methods=["GET"])
def get_public_proof_http(req: func.HttpRequest) -> func.HttpResponse:
    proof_id = req.route_params.get("proof_id", "")

    def operation() -> tuple[int, dict[str, object]]:
        config, repository = _dependencies()
        return get_public_proof(
            proof_id,
            config=config,
            repository=repository,
        )

    return _handle(operation)


@app.route(route="api/proofs/{proof_id}/qr", methods=["GET"])
def get_proof_qr_http(req: func.HttpRequest) -> func.HttpResponse:
    proof_id = req.route_params.get("proof_id", "")
    try:
        config, repository = _dependencies()
        status_code, png = get_proof_qr(
            proof_id,
            config=config,
            repository=repository,
        )
        return func.HttpResponse(
            body=png,
            status_code=status_code,
            mimetype="image/png",
            headers={"Cache-Control": "no-store"},
        )
    except ApiError as error:
        return _json_response(error.to_dict(), error.status_code)
    except Exception:
        logging.exception("Unhandled Proof QR error")
        error = ApiError("ERR_INTERNAL", "internal server error", 500)
        return _json_response(error.to_dict(), error.status_code)


@app.route(route="verify/{proof_id}", methods=["GET"])
def verification_page_http(req: func.HttpRequest) -> func.HttpResponse:
    proof_id = req.route_params.get("proof_id", "")
    try:
        config, repository = _dependencies()
        status_code, html = get_verification_page(
            proof_id,
            config=config,
            repository=repository,
        )
        return func.HttpResponse(
            body=html,
            status_code=status_code,
            mimetype="text/html",
            charset="utf-8",
            headers=_security_headers(),
        )
    except Exception:
        logging.exception("Unhandled verification page error")
        html = get_verification_page_fallback(proof_id)
        return func.HttpResponse(
            body=html,
            status_code=500,
            mimetype="text/html",
            charset="utf-8",
            headers=_security_headers(),
        )


def get_verification_page_fallback(proof_id: str) -> str:
    from reality_cloud.presentation import render_verification_page

    return render_verification_page(
        proof_id=proof_id,
        state="rejected",
    )


@app.route(route="assets/verify.css", methods=["GET"])
def verification_css_http(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        body=load_verification_css(),
        status_code=200,
        mimetype="text/css",
        charset="utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.event_hub_message_trigger(
    arg_name="event",
    event_hub_name="%IOT_HUB_EVENT_HUB_NAME%",
    connection="IOT_HUB_EVENT_CONNECTION",
    consumer_group="%IOT_HUB_CONSUMER_GROUP%",
)
def iot_evidence_telemetry(event: func.EventHubEvent) -> None:
    config, repository = _dependencies()
    envelope = None
    try:
        envelope = parse_telemetry(event.get_body(), event.iothub_metadata)
        process_telemetry(
            envelope,
            config=config,
            repository=repository,
        )
    except Exception as error:
        session_id = None
        device_id = None
        if envelope is not None:
            device_id = envelope.device_id
            raw_session_id = envelope.payload.get("session_id")
            manifest = envelope.payload.get("manifest")
            if not isinstance(raw_session_id, str) and isinstance(manifest, dict):
                raw_session_id = manifest.get("session_id")
            if isinstance(raw_session_id, str):
                session_id = raw_session_id
        try:
            write_audit_log(
                repository,
                "error",
                session_id=session_id,
                device_id=device_id,
                message="IoT Hub telemetry processing failed",
                detail={
                    "failure_code": (
                        error.code
                        if isinstance(error, ApiError)
                        else "ERR_INTERNAL"
                    )
                },
            )
        except Exception:
            logging.exception("Could not persist IoT telemetry error AuditLog")
        logging.exception("IoT Hub telemetry processing failed")
        raise
