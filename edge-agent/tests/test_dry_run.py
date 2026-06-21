import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_core import sha256_file
from reality_edge.dry_run import capture_button_events, run_dry_run


def test_automatic_dry_run_creates_complete_bundle(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    fixed_time = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)

    manifest_path = run_dry_run(
        output_dir=tmp_path,
        fixtures_dir=fixtures_dir,
        device_id="raspi-anchor-01",
        session_id="fixed-session",
        button_count=2,
        clock=lambda: fixed_time,
    )

    expected_names = {
        "image.jpg",
        "audio.wav",
        "manifest.json",
        "manifest.sha256",
        "edge.log",
    }
    assert {path.name for path in manifest_path.parent.iterdir()} == expected_names

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert len(manifest["button_events"]) == 2
    assert manifest["files"]["image"]["sha256"] == sha256_file(
        manifest_path.parent / "image.jpg"
    )
    assert manifest["files"]["audio"]["sha256"] == sha256_file(
        manifest_path.parent / "audio.wav"
    )
    assert (
        manifest_path.parent / "manifest.sha256"
    ).read_text(encoding="ascii").split()[0] == sha256_file(manifest_path)


def test_fixed_inputs_produce_identical_manifests(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    fixed_time = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    first = run_dry_run(
        output_dir=tmp_path / "first",
        fixtures_dir=fixtures_dir,
        device_id="device-1",
        session_id="fixed-session",
        clock=lambda: fixed_time,
    )
    second = run_dry_run(
        output_dir=tmp_path / "second",
        fixtures_dir=fixtures_dir,
        device_id="device-1",
        session_id="fixed-session",
        clock=lambda: fixed_time,
    )

    assert first.read_bytes() == second.read_bytes()


def test_interactive_button_capture_uses_input_and_clock() -> None:
    start = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    times = iter([start + timedelta(seconds=1), start + timedelta(seconds=2)])
    prompts: list[str] = []

    events = capture_button_events(
        count=2,
        started_at=start,
        interactive=True,
        clock=lambda: next(times),
        input_func=lambda prompt: prompts.append(prompt) or "",
    )

    assert len(prompts) == 2
    assert [event["index"] for event in events] == [1, 2]
    assert events[0]["timestamp"] < events[1]["timestamp"]
