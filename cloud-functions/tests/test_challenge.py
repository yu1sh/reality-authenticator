from datetime import datetime, timezone
from uuid import UUID

from reality_cloud.challenge import create_session
from reality_cloud.config import CloudConfig


def test_create_session_is_deterministic_with_injected_sources(
    config: CloudConfig,
) -> None:
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )
    random_values = iter([1, 7])
    fixed_time = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)

    session, response = create_session(
        device_id="raspi-anchor-01",
        config=config,
        clock=lambda: fixed_time,
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: next(random_values),
    )

    assert session["session_id"] == "11111111-1111-4111-8111-111111111111"
    assert session["challenge_nonce"] == "22222222-2222-4222-8222-222222222222"
    assert session["button_count"] == 2
    assert session["voice_code"] == "0007"
    assert session["created_at"] == "2026-06-09T01:00:00.000+00:00"
    assert session["expires_at"] == "2026-06-09T01:00:15.000+00:00"
    assert response["challenge"]["button_count"] == 2


def test_challenge_values_stay_within_required_ranges(
    config: CloudConfig,
) -> None:
    for button_random in range(3):
        for voice_random in (0, 9, 999, 9999):
            random_values = iter([button_random, voice_random])
            session, _ = create_session(
                device_id="raspi-anchor-01",
                config=config,
                clock=lambda: datetime(2026, 6, 9, tzinfo=timezone.utc),
                uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
                randbelow=lambda limit: next(random_values),
            )
            assert 1 <= session["button_count"] <= 3
            assert len(session["voice_code"]) == 4
            assert session["voice_code"].isdigit()


def test_environment_can_extend_real_device_session(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TIME_LIMIT_SECONDS", "30")
    monkeypatch.setenv("GRACE_SECONDS", "15")
    config = CloudConfig.from_environment()
    fixed_time = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)

    session, response = create_session(
        device_id="raspi-anchor-01",
        config=config,
        clock=lambda: fixed_time,
        uuid_factory=lambda: UUID("11111111-1111-4111-8111-111111111111"),
        randbelow=lambda limit: 0,
    )

    assert response["challenge"]["time_limit_seconds"] == 30
    assert session["expires_at"] == "2026-06-09T01:00:45.000+00:00"
