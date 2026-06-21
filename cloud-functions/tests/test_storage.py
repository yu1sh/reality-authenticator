from pathlib import Path

from reality_core import canonical_json_bytes
from reality_cloud.storage import LocalJsonRepository


def test_session_and_manifest_are_written_as_canonical_json(
    repository: LocalJsonRepository,
    session: dict[str, object],
    manifest: dict[str, object],
) -> None:
    repository.save_session(session)
    repository.save_manifest(manifest)

    session_path = repository.root / "sessions" / "session-1.json"
    manifest_path = (
        repository.root / "evidence" / "session-1" / "manifest.json"
    )
    assert session_path.read_bytes() == canonical_json_bytes(session)
    assert manifest_path.read_bytes() == canonical_json_bytes(manifest)
    assert repository.load_session("session-1") == session
    assert repository.load_manifest("session-1") == manifest
    assert not list(repository.root.rglob("*.tmp"))


def test_missing_records_return_none(repository: LocalJsonRepository) -> None:
    assert repository.load_session("missing") is None
    assert repository.load_manifest("missing") is None
    assert repository.load_proof("RP-missing") is None


def test_proof_is_written_as_canonical_json(
    repository: LocalJsonRepository,
) -> None:
    proof = {"proof_id": "RP-proof-1", "session_id": "session-1", "z": 1, "a": 2}

    repository.save_proof(proof)

    proof_path = repository.root / "proofs" / "RP-proof-1.json"
    assert proof_path.read_bytes() == canonical_json_bytes(proof)
    assert repository.load_proof("RP-proof-1") == proof
