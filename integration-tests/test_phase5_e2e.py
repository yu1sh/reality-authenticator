from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    ROOT / "edge-agent" / "src",
    ROOT / "cloud-functions",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from reality_cloud.config import CloudConfig
from reality_cloud.handlers import (
    get_verification_page,
    ingest_evidence,
    issue_proof,
    start_session,
    verify_proof,
)
from reality_cloud.storage import LocalJsonRepository
from reality_edge.dry_run import run_dry_run


def test_start_to_verification_page_end_to_end(tmp_path: Path) -> None:
    created_at = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    cloud_config = CloudConfig(
        allowed_device_ids=frozenset({"raspi-anchor-01"}),
        local_data_dir=tmp_path / "cloud",
        device_api_key="test-device-key",
        stub_signing_secret="test-signing-secret",
        public_web_base_url="http://localhost:7071",
    )
    repository = LocalJsonRepository(cloud_config.local_data_dir)
    uuids = iter(
        [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
    )
    random_values = iter([1, 7])
    _, session_response = start_session(
        {"device_id": "raspi-anchor-01"},
        config=cloud_config,
        repository=repository,
        clock=lambda: created_at,
        uuid_factory=lambda: next(uuids),
        randbelow=lambda limit: next(random_values),
    )
    challenge = dict(session_response["challenge"])
    fixtures = ROOT / "edge-agent" / "fixtures" / "dry_run"
    manifest_path = run_dry_run(
        output_dir=tmp_path / "evidence",
        fixtures_dir=fixtures,
        device_id="raspi-anchor-01",
        session_id=str(session_response["session_id"]),
        button_count=int(challenge["button_count"]),
        challenge=challenge,
        clock=lambda: created_at + timedelta(seconds=1),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ingest_status, ingest_response = ingest_evidence(
        manifest,
        repository=repository,
        clock=lambda: created_at + timedelta(seconds=5),
    )
    issue_status, issue_response = issue_proof(
        {"session_id": session_response["session_id"]},
        config=cloud_config,
        repository=repository,
        clock=lambda: created_at + timedelta(seconds=6),
        uuid_factory=lambda: UUID("33333333-3333-4333-8333-333333333333"),
    )
    proof_id = str(issue_response["proof_id"])
    verify_status, verification = verify_proof(
        proof_id,
        config=cloud_config,
        repository=repository,
    )
    page_status, html = get_verification_page(
        proof_id,
        config=cloud_config,
        repository=repository,
    )

    assert ingest_status == 200
    assert ingest_response["accepted"] is True
    assert issue_status == 201
    assert issue_response["verification_url"].endswith(f"/verify/{proof_id}")
    assert verify_status == 200
    assert verification["valid"] is False
    assert page_status == 200
    assert "WARNING" in html
