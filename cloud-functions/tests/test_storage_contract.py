from pathlib import Path

import pytest

from reality_cloud.storage import LocalJsonRepository
from reality_cloud.storage_contract import StorageConflict


def test_local_repository_etag_replace_and_conflict(tmp_path: Path) -> None:
    repository = LocalJsonRepository(tmp_path)
    session = {"session_id": "session-1", "status": "challenge_issued"}

    created = repository.create_session(session)
    changed = dict(session, status="evidence_uploaded")
    replaced = repository.replace_session(changed, created.etag)

    assert replaced.value == changed
    assert replaced.etag != created.etag
    with pytest.raises(StorageConflict):
        repository.replace_session(dict(changed, status="failed"), created.etag)


def test_local_repository_has_no_upload_or_byte_verification(tmp_path: Path) -> None:
    repository = LocalJsonRepository(tmp_path)

    assert repository.create_upload_targets("session-1", "2026-06-15T00:00:00Z") is None
    assert repository.verify_evidence_files({}).verified is False
