from pathlib import Path
from types import SimpleNamespace

import pytest

import reality_edge.main as main_module
from reality_edge.main import main


def test_cli_dry_run_prints_manifest_and_hash(
    tmp_path: Path, fixtures_dir: Path, capsys
) -> None:
    exit_code = main(
        [
            "--dry-run",
            "--device-id",
            "device-1",
            "--session-id",
            "session-1",
            "--button-count",
            "2",
            "--output-dir",
            str(tmp_path),
            "--fixtures-dir",
            str(fixtures_dir),
            "--fixed-time",
            "2026-06-09T01:00:00+00:00",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert "Manifest:" in output.out
    assert "SHA-256:" in output.out
    assert (tmp_path / "session-1" / "manifest.json").is_file()


def test_cli_rejects_non_dry_run(capsys) -> None:
    assert main([]) == 1
    assert "select exactly one" in capsys.readouterr().err


def test_cli_rejects_both_capture_modes(capsys) -> None:
    assert main(["--dry-run", "--real-device"]) == 1
    assert "select exactly one" in capsys.readouterr().err


def test_real_device_cloud_sync_requires_full_media(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")

    assert main(["--real-device", "--cloud-sync", "--no-camera"]) == 1

    assert "cannot be used with --cloud-sync" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argument",
    [
        ["--session-id", "fixed-session"],
        ["--fixed-time", "2026-06-09T01:00:00+00:00"],
        ["--button-count", "2"],
    ],
)
def test_cloud_sync_rejects_offline_only_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    argument: list[str],
) -> None:
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")

    assert main(["--dry-run", "--cloud-sync", *argument]) == 1

    assert "cannot be used with --cloud-sync" in capsys.readouterr().err


def test_cloud_sync_cli_prints_proof_and_returns_failure_for_invalid_verify(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")
    monkeypatch.setattr(
        main_module,
        "run_cloud_sync",
        lambda **kwargs: SimpleNamespace(
            manifest_path=manifest_path,
            proof_id="RP-1",
            verification_url="http://localhost:7071/verify/RP-1",
            qr_url="http://localhost:7071/api/proofs/RP-1/qr",
            verification={
                "valid": False,
                "status": "INVALID",
                "checks": {"signature": False},
            },
        ),
    )

    exit_code = main(
        [
            "--dry-run",
            "--cloud-sync",
            "--output-dir",
            str(tmp_path),
            "--fixtures-dir",
            str(fixtures_dir),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert "Proof ID: RP-1" in output.out
    assert "Verification: INVALID" in output.out


def test_cloud_sync_cli_prints_warning_and_returns_failure(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEVICE_API_KEY", "test-key")
    monkeypatch.setattr(
        main_module,
        "run_cloud_sync",
        lambda **kwargs: SimpleNamespace(
            manifest_path=manifest_path,
            proof_id="RP-1",
            verification_url="http://localhost:7071/verify/RP-1",
            qr_url="http://localhost:7071/api/proofs/RP-1/qr",
            verification={
                "valid": False,
                "status": "WARNING",
                "checks": {"signature": True, "image_hash": None},
            },
        ),
    )

    exit_code = main(
        [
            "--dry-run",
            "--cloud-sync",
            "--output-dir",
            str(tmp_path),
            "--fixtures-dir",
            str(fixtures_dir),
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 1
    assert "Verification: WARNING" in output.out
