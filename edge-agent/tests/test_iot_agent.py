from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from reality_edge.iot_agent import IotAgentError, IotEdgeAgent, ProcessedCommandStore


class Transport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def receive(self) -> dict[str, object]:
        raise AssertionError("not used")

    async def send(self, payload) -> None:
        self.sent.append(dict(payload))


async def no_sleep(seconds: float) -> None:
    del seconds


def test_process_command_uploads_manifest_and_ignores_duplicate(
    tmp_path: Path,
) -> None:
    transport = Transport()
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "session-1",
                "device_id": "raspi-anchor-01",
                "challenge": {"button_count": 2},
            }
        ),
        encoding="utf-8",
    )
    uploads: list[tuple[dict[str, object], Path]] = []

    def capture(session_id, challenge, expires_at):
        assert session_id == "session-1"
        assert challenge["button_count"] == 2
        assert expires_at
        return manifest_path

    def upload(*, upload, manifest_path):
        uploads.append((upload, manifest_path))

    agent = IotEdgeAgent(
        transport=transport,
        device_id="raspi-anchor-01",
        capture=capture,
        command_store=ProcessedCommandStore(tmp_path / "commands.json"),
        uploader=upload,
    )
    command = {
        "message_type": "start_session",
        "command_id": "session-1",
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "challenge": {"button_count": 2},
        "expires_at": "2099-06-15T01:00:00+00:00",
        "upload": {"mode": "sas_url"},
    }

    asyncio.run(agent.process_command(command))
    asyncio.run(agent.process_command(command))

    assert len(uploads) == 1
    assert transport.sent[0]["status"] == "challenge_received"
    assert transport.sent[1]["status"] == "capturing"
    assert transport.sent[2]["message_type"] == "evidence_manifest"
    assert transport.sent[3]["status"] == "duplicate_ignored"
    assert "sync_status=completed" in (
        manifest_path.parent / "edge.log"
    ).read_text()


@pytest.mark.parametrize(
    ("device_id", "expires_at", "code"),
    [
        ("other-device", "2099-06-15T01:00:00+00:00", "ERR_DEVICE_MISMATCH"),
        ("raspi-anchor-01", "2000-01-01T00:00:00+00:00", "ERR_SESSION_EXPIRED"),
    ],
)
def test_process_command_rejects_wrong_device_or_expired_command(
    tmp_path: Path,
    device_id: str,
    expires_at: str,
    code: str,
) -> None:
    agent = IotEdgeAgent(
        transport=Transport(),
        device_id="raspi-anchor-01",
        capture=lambda *args: pytest.fail("capture must not run"),
        command_store=ProcessedCommandStore(tmp_path / "commands.json"),
    )

    with pytest.raises(IotAgentError) as caught:
        asyncio.run(
            agent.process_command(
                {
                    "message_type": "start_session",
                    "command_id": "session-1",
                    "session_id": "session-1",
                    "device_id": device_id,
                    "challenge": {"button_count": 2},
                    "expires_at": expires_at,
                    "upload": {"mode": "sas_url"},
                }
            )
        )

    assert caught.value.code == code


def test_process_command_requires_command_id_to_match_session_id(
    tmp_path: Path,
) -> None:
    agent = IotEdgeAgent(
        transport=Transport(),
        device_id="raspi-anchor-01",
        capture=lambda *args: pytest.fail("capture must not run"),
        command_store=ProcessedCommandStore(tmp_path / "commands.json"),
    )

    with pytest.raises(IotAgentError) as caught:
        asyncio.run(
            agent.process_command(
                {
                    "message_type": "start_session",
                    "command_id": "other-command",
                    "session_id": "session-1",
                    "device_id": "raspi-anchor-01",
                    "challenge": {"button_count": 2},
                    "expires_at": "2099-06-15T01:00:00+00:00",
                    "upload": {"mode": "sas_url"},
                }
            )
        )

    assert caught.value.code == "ERR_INVALID_COMMAND"


def test_unprocessed_command_retry_reuses_existing_manifest(
    tmp_path: Path,
) -> None:
    class FlakyTransport(Transport):
        def __init__(self) -> None:
            super().__init__()
            self.manifest_failures = 3

        async def send(self, payload) -> None:
            if (
                payload["message_type"] == "evidence_manifest"
                and self.manifest_failures
            ):
                self.manifest_failures -= 1
                raise OSError("temporary IoT failure")
            await super().send(payload)

    transport = FlakyTransport()
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    manifest_path = session_dir / "manifest.json"
    challenge = {"button_count": 2}
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "session-1",
                "device_id": "raspi-anchor-01",
                "challenge": challenge,
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "edge.log").write_text("status=completed\n")
    captures = 0
    uploads = 0

    def capture(*args):
        nonlocal captures
        captures += 1
        return manifest_path

    def upload(**kwargs):
        nonlocal uploads
        uploads += 1

    agent = IotEdgeAgent(
        transport=transport,
        device_id="raspi-anchor-01",
        capture=capture,
        command_store=ProcessedCommandStore(tmp_path / "commands.json"),
        uploader=upload,
        sleep=no_sleep,
    )
    command = {
        "message_type": "start_session",
        "command_id": "session-1",
        "session_id": "session-1",
        "device_id": "raspi-anchor-01",
        "challenge": challenge,
        "expires_at": "2099-06-15T01:00:00+00:00",
        "upload": {"mode": "sas_url"},
    }

    with pytest.raises(IotAgentError) as caught:
        asyncio.run(agent.process_command(command))
    assert caught.value.code == "ERR_IOT_UNAVAILABLE"

    asyncio.run(agent.process_command(command))

    assert captures == 0
    assert uploads == 2
    assert agent.command_store.contains("session-1")
    log = (session_dir / "edge.log").read_text()
    assert "sync_status=failed" in log
    assert "failure_code=ERR_IOT_UNAVAILABLE" in log
    assert "sync_status=completed" in log


def test_heartbeat_sends_online_status(tmp_path: Path) -> None:
    transport = Transport()
    sleeps = 0

    async def sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        raise asyncio.CancelledError

    agent = IotEdgeAgent(
        transport=transport,
        device_id="raspi-anchor-01",
        capture=lambda *args: Path("unused"),
        command_store=ProcessedCommandStore(tmp_path / "commands.json"),
        sleep=sleep,
    )

    try:
        asyncio.run(agent.heartbeat())
    except asyncio.CancelledError:
        pass

    assert sleeps == 1
    assert transport.sent[0]["message_type"] == "heartbeat"
