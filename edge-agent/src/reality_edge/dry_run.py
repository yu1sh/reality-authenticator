"""Hardware-independent evidence capture."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from .evidence import build_evidence_manifest, write_evidence_bundle

Clock = Callable[[], datetime]
InputFunction = Callable[[str], str]

DEFAULT_SENSORS: dict[str, int | float] = {
    "temperature_c": 25.6,
    "humidity_percent": 42.8,
    "light_raw": 734,
    "sound_raw": 312,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.isoformat(timespec="milliseconds")


def _automatic_event_times(started_at: datetime, count: int) -> Iterator[datetime]:
    for index in range(count):
        yield started_at + timedelta(seconds=index + 1)


def capture_button_events(
    *,
    count: int,
    started_at: datetime,
    interactive: bool,
    clock: Clock,
    input_func: InputFunction,
) -> list[dict[str, object]]:
    if count < 1:
        raise ValueError("button count must be at least 1")

    if interactive:
        event_times = []
        for index in range(count):
            input_func(f"Press Enter for button event {index + 1}/{count}: ")
            event_times.append(clock())
    else:
        event_times = list(_automatic_event_times(started_at, count))

    return [
        {"index": index, "timestamp": _iso8601(timestamp)}
        for index, timestamp in enumerate(event_times, start=1)
    ]


def run_dry_run(
    *,
    output_dir: Path,
    fixtures_dir: Path,
    device_id: str,
    session_id: str | None = None,
    button_count: int = 2,
    interactive: bool = False,
    edge_version: str = "0.1.0",
    sensors: dict[str, int | float] | None = None,
    challenge: Mapping[str, object] | None = None,
    clock: Clock = utc_now,
    input_func: InputFunction = input,
) -> Path:
    """Create a dry-run evidence bundle and return its manifest path."""

    actual_session_id = session_id or str(uuid4())
    started_at = clock()
    button_events = capture_button_events(
        count=button_count,
        started_at=started_at,
        interactive=interactive,
        clock=clock,
        input_func=input_func,
    )
    finished_at = clock() if interactive else started_at + timedelta(
        seconds=button_count + 1
    )

    image_source = fixtures_dir / "image.jpg"
    audio_source = fixtures_dir / "audio.wav"
    manifest = build_evidence_manifest(
        session_id=actual_session_id,
        device_id=device_id,
        edge_started_at=_iso8601(started_at),
        edge_finished_at=_iso8601(finished_at),
        button_events=button_events,
        sensors=sensors or dict(DEFAULT_SENSORS),
        image_path=image_source,
        audio_path=audio_source,
        edge_version=edge_version,
        challenge=challenge,
    )

    log_text = (
        f"session_id={actual_session_id}\n"
        f"device_id={device_id}\n"
        f"mode={'interactive' if interactive else 'automatic'}\n"
        f"button_events={len(button_events)}\n"
        "status=completed\n"
    )
    return write_evidence_bundle(
        output_dir=output_dir,
        manifest=manifest,
        image_source=image_source,
        audio_source=audio_source,
        log_text=log_text,
    )
