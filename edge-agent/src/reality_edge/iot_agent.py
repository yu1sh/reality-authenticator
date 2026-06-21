"""Long-running Azure IoT Hub Edge Agent."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .blob_upload import BlobUploadError, upload_evidence_files
from .hardware.errors import HardwareError


class IotAgentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DeviceTransport(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def receive(self) -> dict[str, object]: ...

    async def send(self, payload: Mapping[str, object]) -> None: ...


class AzureDeviceTransport:
    def __init__(self, client: object, message_factory: Callable[[str], object]) -> None:
        self.client = client
        self.message_factory = message_factory

    @classmethod
    def from_connection_string(cls, connection_string: str) -> "AzureDeviceTransport":
        try:
            from azure.iot.device import Message
            from azure.iot.device.aio import IoTHubDeviceClient
        except ImportError as error:
            raise IotAgentError(
                "ERR_IOT_UNAVAILABLE",
                "azure-iot-device is not installed",
            ) from error
        client = IoTHubDeviceClient.create_from_connection_string(
            connection_string
        )
        return cls(client, Message)

    async def connect(self) -> None:
        await self.client.connect()

    async def disconnect(self) -> None:
        await self.client.disconnect()

    async def receive(self) -> dict[str, object]:
        message = await self.client.receive_message()
        raw = getattr(message, "data", message)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, bytes):
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "IoT Hub command body is invalid",
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "IoT Hub command is not valid JSON",
            ) from error
        if not isinstance(payload, dict):
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "IoT Hub command must be a JSON object",
            )
        return payload

    async def send(self, payload: Mapping[str, object]) -> None:
        message = self.message_factory(
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        message.content_type = "application/json"
        message.content_encoding = "utf-8"
        await self.client.send_message(message)


CaptureFunction = Callable[[str, dict[str, object], str], Path]
UploadFunction = Callable[..., None]
SleepFunction = Callable[[float], Awaitable[None]]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ProcessedCommandStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._values = self._load()

    def _load(self) -> set[str]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return set()
        except json.JSONDecodeError as error:
            raise IotAgentError(
                "ERR_COMMAND_STORE",
                "processed command store is corrupt",
            ) from error
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise IotAgentError(
                "ERR_COMMAND_STORE",
                "processed command store is invalid",
            )
        return set(value)

    def contains(self, command_id: str) -> bool:
        return command_id in self._values

    def add(self, command_id: str) -> None:
        self._values.add(command_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(sorted(self._values), separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


class IotEdgeAgent:
    def __init__(
        self,
        *,
        transport: DeviceTransport,
        device_id: str,
        capture: CaptureFunction,
        command_store: ProcessedCommandStore,
        heartbeat_seconds: int = 60,
        uploader: UploadFunction = upload_evidence_files,
        sleep: SleepFunction = asyncio.sleep,
    ) -> None:
        self.transport = transport
        self.device_id = device_id
        self.capture = capture
        self.command_store = command_store
        self.heartbeat_seconds = heartbeat_seconds
        self.uploader = uploader
        self.sleep = sleep

    async def _send(self, message_type: str, **payload: object) -> None:
        message = {
            "message_type": message_type,
            "device_id": self.device_id,
            "sent_at": _utc_timestamp(),
            **payload,
        }
        for attempt in range(3):
            try:
                await self.transport.send(message)
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if attempt == 2:
                    raise IotAgentError(
                        "ERR_IOT_UNAVAILABLE",
                        "IoT Hub telemetry send failed",
                    ) from error
                await self.sleep(float(attempt + 1))

    async def heartbeat(self) -> None:
        while True:
            try:
                await self._send("heartbeat", status="online")
            except IotAgentError:
                pass
            await self.sleep(self.heartbeat_seconds)

    def _load_existing_manifest(
        self,
        *,
        session_id: str,
        challenge: Mapping[str, object],
    ) -> Path | None:
        path = self.command_store.path.parent / session_id / "manifest.json"
        if not path.exists():
            return None
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise IotAgentError(
                "ERR_INVALID_MANIFEST",
                "existing Manifest could not be reused",
            ) from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("session_id") != session_id
            or manifest.get("device_id") != self.device_id
            or manifest.get("challenge") != dict(challenge)
        ):
            raise IotAgentError(
                "ERR_INVALID_MANIFEST",
                "existing Manifest does not match the command",
            )
        return path

    @staticmethod
    def _append_sync_log(
        manifest_path: Path | None,
        *,
        status: str,
        failure_code: str | None = None,
    ) -> None:
        if manifest_path is None:
            return
        try:
            with (manifest_path.parent / "edge.log").open(
                "a", encoding="utf-8"
            ) as log:
                log.write(f"sync_status={status}\n")
                if failure_code:
                    log.write(f"failure_code={failure_code}\n")
        except OSError:
            pass

    async def process_command(self, command: Mapping[str, object]) -> None:
        if command.get("message_type") != "start_session":
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "unsupported IoT Hub command",
            )
        command_id = command.get("command_id")
        session_id = command.get("session_id")
        command_device_id = command.get("device_id")
        challenge = command.get("challenge")
        expires_at = command.get("expires_at")
        if not all(
            (
                isinstance(command_id, str) and command_id,
                isinstance(session_id, str) and session_id,
                isinstance(command_device_id, str) and command_device_id,
                isinstance(challenge, dict),
                isinstance(expires_at, str) and expires_at,
            )
        ):
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "StartSession command is incomplete",
            )
        if command_device_id != self.device_id:
            raise IotAgentError(
                "ERR_DEVICE_MISMATCH",
                "StartSession command targets a different device",
            )
        if command_id != session_id:
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "command_id must match session_id",
            )
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "StartSession expiry is invalid",
            ) from error
        if expires.tzinfo is None or expires.utcoffset() is None:
            raise IotAgentError(
                "ERR_INVALID_COMMAND",
                "StartSession expiry must include a UTC offset",
            )
        if datetime.now(timezone.utc) > expires:
            raise IotAgentError(
                "ERR_SESSION_EXPIRED",
                "StartSession command has expired",
            )
        if self.command_store.contains(command_id):
            await self._send(
                "device_status",
                session_id=session_id,
                status="duplicate_ignored",
            )
            return

        await self._send(
            "device_status",
            session_id=session_id,
            status="challenge_received",
        )
        manifest_path: Path | None = None
        try:
            await self._send(
                "device_status",
                session_id=session_id,
                status="capturing",
            )
            manifest_path = self._load_existing_manifest(
                session_id=session_id,
                challenge=challenge,
            )
            if manifest_path is None:
                manifest_path = self.capture(
                    session_id,
                    dict(challenge),
                    expires_at,
                )
            upload = command.get("upload")
            if not isinstance(upload, dict):
                raise IotAgentError(
                    "ERR_UPLOAD_REQUIRED",
                    "StartSession command does not contain upload targets",
                )
            self.uploader(
                upload=upload,
                manifest_path=manifest_path,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise IotAgentError(
                    "ERR_INVALID_MANIFEST",
                    "generated Manifest is invalid",
                )
            await self._send("evidence_manifest", manifest=manifest)
            self.command_store.add(command_id)
            self._append_sync_log(manifest_path, status="completed")
        except (HardwareError, BlobUploadError, IotAgentError) as error:
            self._append_sync_log(
                manifest_path,
                status="failed",
                failure_code=error.code,
            )
            await self._send(
                "device_status",
                session_id=session_id,
                status="failed",
                failure_code=error.code,
            )
            raise
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._append_sync_log(
                manifest_path,
                status="failed",
                failure_code="ERR_CAPTURE_FAILED",
            )
            await self._send(
                "device_status",
                session_id=session_id,
                status="failed",
                failure_code="ERR_CAPTURE_FAILED",
            )
            raise IotAgentError(
                "ERR_CAPTURE_FAILED",
                "command processing failed",
            ) from error

    async def run(self) -> None:
        await self.transport.connect()
        heartbeat_task = asyncio.create_task(self.heartbeat())
        try:
            while True:
                try:
                    command = await self.transport.receive()
                    await self.process_command(command)
                except (IotAgentError, HardwareError, BlobUploadError):
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await self.sleep(1)
                    continue
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            await self.transport.disconnect()
