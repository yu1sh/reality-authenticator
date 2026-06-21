"""IoT Hub command dispatch and telemetry parsing."""

from __future__ import annotations

import json
import base64
import binascii
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen


class IotUnavailable(RuntimeError):
    """IoT Hub could not complete an operation."""


class CommandDispatcher(Protocol):
    def send_start_session(
        self,
        device_id: str,
        command: Mapping[str, object],
    ) -> None: ...


class AzureIotHubCommandDispatcher:
    def __init__(
        self,
        *,
        host_name: str,
        policy_name: str,
        policy_key: str,
        opener=urlopen,
        clock=time.time,
    ) -> None:
        self.host_name = host_name
        self.policy_name = policy_name
        self.policy_key = policy_key
        self.opener = opener
        self.clock = clock

    @classmethod
    def from_connection_string(
        cls, connection_string: str
    ) -> "AzureIotHubCommandDispatcher":
        try:
            values = dict(
                part.split("=", 1)
                for part in connection_string.split(";")
                if "=" in part
            )
            host_name = values["HostName"]
            policy_name = values["SharedAccessKeyName"]
            policy_key = values["SharedAccessKey"]
        except (KeyError, ValueError) as error:
            raise IotUnavailable(
                "IoT Hub service connection string is invalid"
            ) from error
        if not all((host_name, policy_name, policy_key)):
            raise IotUnavailable(
                "IoT Hub service connection string is incomplete"
            )
        return cls(
            host_name=host_name,
            policy_name=policy_name,
            policy_key=policy_key,
        )

    def _authorization(self) -> str:
        resource_uri = self.host_name.lower()
        encoded_uri = quote(resource_uri, safe="")
        expiry = int(self.clock()) + 300
        to_sign = f"{encoded_uri}\n{expiry}".encode("utf-8")
        try:
            key = base64.b64decode(self.policy_key, validate=True)
        except (ValueError, binascii.Error) as error:
            raise IotUnavailable("IoT Hub service key is invalid") from error
        signature = base64.b64encode(
            hmac.new(key, to_sign, hashlib.sha256).digest()
        ).decode("ascii")
        return (
            f"SharedAccessSignature sr={encoded_uri}"
            f"&sig={quote(signature, safe='')}"
            f"&se={expiry}&skn={quote(self.policy_name, safe='')}"
        )

    def send_start_session(
        self,
        device_id: str,
        command: Mapping[str, object],
    ) -> None:
        request = Request(
            (
                f"https://{self.host_name}/devices/"
                f"{quote(device_id, safe='')}/messages/deviceBound"
                "?api-version=2021-04-12"
            ),
            data=json.dumps(
                dict(command),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Authorization": self._authorization(),
                "Content-Type": "application/json; charset=utf-8",
                "iothub-app-message_type": "start_session",
            },
            method="POST",
        )
        try:
            response = self.opener(request, timeout=10)
            try:
                response.read()
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except Exception as error:
            raise IotUnavailable("IoT Hub command dispatch failed") from error


def create_command_dispatcher(config: object) -> CommandDispatcher | None:
    if not getattr(config, "use_iot_hub", False):
        return None
    connection_string = getattr(
        config, "iot_hub_service_connection_string", None
    )
    if not connection_string:
        raise IotUnavailable("IoT Hub service connection is not configured")
    return AzureIotHubCommandDispatcher.from_connection_string(connection_string)


@dataclass(frozen=True)
class TelemetryEnvelope:
    message_type: str
    device_id: str
    payload: dict[str, object]


def parse_telemetry(
    body: bytes,
    metadata: Mapping[str, str] | None,
) -> TelemetryEnvelope:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("telemetry body must be a JSON object") from error
    if not isinstance(value, dict):
        raise ValueError("telemetry body must be a JSON object")

    metadata = metadata or {}
    device_id = (
        metadata.get("connection-device-id")
        or metadata.get("iothub-connection-device-id")
        or metadata.get("device-id")
    )
    message_type = value.get("message_type")
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("IoT Hub device identity is missing")
    if not isinstance(message_type, str) or not message_type:
        raise ValueError("telemetry message_type is missing")
    return TelemetryEnvelope(message_type, device_id, value)
