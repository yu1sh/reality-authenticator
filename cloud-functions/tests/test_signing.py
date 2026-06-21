from reality_cloud.signing import sign_record_hash, verify_record_signature


def test_stub_signature_is_unpadded_base64url_and_verifies() -> None:
    record_hash = "ab" * 32

    signature = sign_record_hash(record_hash, "secret")

    assert "=" not in signature
    assert verify_record_signature(record_hash, signature, "secret")
    assert not verify_record_signature(record_hash, signature, "other-secret")


def test_tampered_hash_or_signature_fails_verification() -> None:
    signature = sign_record_hash("ab" * 32, "secret")

    assert not verify_record_signature("cd" * 32, signature, "secret")
    assert not verify_record_signature("ab" * 32, f"{signature}x", "secret")
