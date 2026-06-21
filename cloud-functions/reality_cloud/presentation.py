"""Public Proof projection and server-rendered verification pages."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from string import Template
from typing import Mapping

from .qr import verification_page_url

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WEB_ROOT = Path(__file__).resolve().parents[1] / "web"

STATE_MESSAGES = {
    "valid": "すべての完全性検証に成功しました。",
    "warning": "署名または証拠媒体の一部を完全には確認できませんでした。",
    "invalid": "完全性検証に失敗しました。この記録を信頼しないでください。",
    "rejected": "記録は存在しますが、検証処理を完了できませんでした。",
    "not_found": "指定された Proof ID の証明レコードはありません。",
}
CHECK_LABELS = {
    "proof_identity": "Proof と Session の整合性",
    "manifest_hash": "Manifest Hash",
    "record_hash": "Record Hash",
    "signature": "電子署名",
    "image_hash": "画像 SHA-256",
    "audio_hash": "音声 SHA-256",
    "device_status": "端末の有効状態",
}
WARNING_MESSAGES = {
    "STUB_SIGNATURE_NOT_KEY_VAULT": (
        "ローカル開発用署名のため、Azure Key Vault 署名ではありません。"
    ),
    "EVIDENCE_BYTES_NOT_VERIFIED": (
        "画像または音声の実体を再取得してハッシュ確認できませんでした。"
    ),
    "SIGNATURE_VERIFICATION_UNAVAILABLE": (
        "署名サービスに接続できず、電子署名を確認できませんでした。"
    ),
    "DEVICE_STATUS_NOT_VERIFIED": (
        "登録端末の現在の有効状態を確認できませんでした。"
    ),
}
CHALLENGE_TYPE_LABELS = {
    "button_and_voice": "ボタン操作と音声記録",
}
CHALLENGE_RESULT_LABELS = {
    "verified": "検証済み",
}
VOICE_VERIFICATION_LABELS = {
    "not_performed": "音声認識は未実施（ファイルハッシュのみ検証）",
}


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is invalid")
    return value


def _required_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} is invalid")
    return value


def public_proof_projection(
    proof: Mapping[str, object],
    public_web_base_url: str,
    manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return only fields safe and necessary for public verification."""

    proof_id = _required_string(proof.get("proof_id"), "proof_id")
    manifest_hash = _required_string(proof.get("manifest_hash"), "manifest_hash")
    record_hash = _required_string(proof.get("record_hash"), "record_hash")
    if not _HASH_PATTERN.fullmatch(manifest_hash):
        raise ValueError("manifest_hash is invalid")
    if not _HASH_PATTERN.fullmatch(record_hash):
        raise ValueError("record_hash is invalid")

    challenge = proof.get("challenge")
    if not isinstance(challenge, dict):
        raise ValueError("challenge is invalid")

    key_id = proof.get("key_id", proof.get("signature_key_id"))
    signed_at = proof.get("signed_at", proof.get("created_at"))
    signature_algorithm = _required_string(
        proof.get("signature_algorithm"),
        "signature_algorithm",
    )
    sensors = manifest.get("sensors") if isinstance(manifest, Mapping) else None
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    files = files if isinstance(files, Mapping) else {}
    image = files.get("image")
    audio = files.get("audio")
    image = image if isinstance(image, Mapping) else {}
    audio = audio if isinstance(audio, Mapping) else {}
    return {
        "schema_version": _required_string(
            proof.get("schema_version"), "schema_version"
        ),
        "proof_id": proof_id,
        "device_id": _required_string(proof.get("device_id"), "device_id"),
        "captured_at": _required_string(proof.get("captured_at"), "captured_at"),
        "created_at": _required_string(proof.get("created_at"), "created_at"),
        "challenge": {
            "type": _required_string(challenge.get("type"), "challenge.type"),
            "button_count_required": _required_integer(
                challenge.get("button_count_required"),
                "challenge.button_count_required",
            ),
            "button_count_actual": _required_integer(
                challenge.get("button_count_actual"),
                "challenge.button_count_actual",
            ),
            "result": _required_string(
                challenge.get("result"),
                "challenge.result",
            ),
            "voice_verification": _required_string(
                challenge.get("voice_verification"),
                "challenge.voice_verification",
            ),
        },
        "manifest_hash": manifest_hash,
        "record_hash": record_hash,
        "signature_algorithm": signature_algorithm,
        "key_id": _required_string(key_id, "key_id"),
        "signed_at": _required_string(signed_at, "signed_at"),
        "signature": _required_string(proof.get("signature"), "signature"),
        "public_key": (
            dict(proof["public_key"])
            if isinstance(proof.get("public_key"), dict)
            else None
        ),
        "verification_url": verification_page_url(
            public_web_base_url,
            proof_id,
        ),
        "sensors": dict(sensors) if isinstance(sensors, Mapping) else {},
        "image_sha256": image.get("sha256"),
        "audio_sha256": audio.get("sha256"),
    }


def verification_state(verification: Mapping[str, object]) -> str:
    status = verification.get("status")
    if status == "VALID":
        return "valid"
    if status == "WARNING":
        return "warning"
    return "invalid"


def _check_rows(checks: object) -> str:
    if not isinstance(checks, dict):
        return '<li class="check check-warning">検証項目を取得できません</li>'
    rows = []
    for name in sorted(checks):
        result = checks[name]
        label = escape(CHECK_LABELS.get(str(name), str(name)))
        if result is True:
            status = "一致"
            css_class = "check-pass"
        elif result is None:
            status = "未確認"
            css_class = "check-warning"
        else:
            status = "不一致"
            css_class = "check-fail"
        rows.append(
            f'<li class="check {css_class}"><span>{label}</span>'
            f"<strong>{status}</strong></li>"
        )
    return "".join(rows)


def _warning_rows(warnings: object) -> str:
    if not isinstance(warnings, list) or not warnings:
        return "<li>警告はありません。</li>"
    return "".join(
        f"<li>{escape(WARNING_MESSAGES.get(str(warning), str(warning)))}</li>"
        for warning in warnings
    )


def _sensor_rows(sensors: object) -> str:
    if not isinstance(sensors, dict) or not sensors:
        return "<div><dt>センサ</dt><dd>利用できません</dd></div>"
    return "".join(
        f"<div><dt>{escape(str(name))}</dt><dd>{escape(str(value))}</dd></div>"
        for name, value in sorted(sensors.items())
    )


def render_verification_page(
    *,
    proof_id: str,
    state: str,
    proof: Mapping[str, object] | None = None,
    verification: Mapping[str, object] | None = None,
) -> str:
    """Render the verification page with all dynamic values escaped."""

    if state == "accepted":
        state = "valid"
    if state not in STATE_MESSAGES:
        raise ValueError("unsupported verification state")

    public_proof = dict(proof or {})
    challenge = public_proof.get("challenge")
    challenge = challenge if isinstance(challenge, dict) else {}
    verification = dict(verification or {})
    qr_path = (
        f"/api/proofs/{escape(proof_id, quote=True)}/qr"
        if proof is not None
        else ""
    )
    qr_markup = (
        f'<img class="qr" src="{qr_path}" alt="検証ページの QR コード">'
        if qr_path
        else '<div class="qr-placeholder">QR を利用できません</div>'
    )

    template = Template((_WEB_ROOT / "verify.html").read_text(encoding="utf-8"))
    values = {
        "state": escape(state.replace("_", " ").upper()),
        "state_class": escape(state),
        "message": escape(STATE_MESSAGES[state]),
        "proof_id": escape(proof_id),
        "device_id": escape(str(public_proof.get("device_id", "利用できません"))),
        "captured_at": escape(
            str(public_proof.get("captured_at", "利用できません"))
        ),
        "created_at": escape(str(public_proof.get("created_at", "利用できません"))),
        "challenge_type": escape(
            CHALLENGE_TYPE_LABELS.get(
                str(challenge.get("type")),
                str(challenge.get("type", "利用できません")),
            )
        ),
        "button_required": escape(
            str(challenge.get("button_count_required", "利用できません"))
        ),
        "button_actual": escape(
            str(challenge.get("button_count_actual", "利用できません"))
        ),
        "challenge_result": escape(
            CHALLENGE_RESULT_LABELS.get(
                str(challenge.get("result")),
                str(challenge.get("result", "利用できません")),
            )
        ),
        "voice_verification": escape(
            VOICE_VERIFICATION_LABELS.get(
                str(challenge.get("voice_verification")),
                str(challenge.get("voice_verification", "利用できません")),
            )
        ),
        "manifest_hash": escape(
            str(public_proof.get("manifest_hash", "利用できません"))
        ),
        "record_hash": escape(
            str(public_proof.get("record_hash", "利用できません"))
        ),
        "signature_algorithm": escape(
            str(public_proof.get("signature_algorithm", "利用できません"))
        ),
        "key_id": escape(str(public_proof.get("key_id", "利用できません"))),
        "signed_at": escape(str(public_proof.get("signed_at", "利用できません"))),
        "signature": escape(
            str(public_proof.get("signature", "利用できません"))
        ),
        "sensor_rows": _sensor_rows(public_proof.get("sensors")),
        "image_sha256": escape(
            str(public_proof.get("image_sha256") or "利用できません")
        ),
        "audio_sha256": escape(
            str(public_proof.get("audio_sha256") or "利用できません")
        ),
        "signing_notice": escape(
            "この Proof はローカル開発用署名を使用しています。"
            if public_proof.get("signature_algorithm") == "STUB-HS256"
            else (
                "この Proof は Azure Key Vault の管理鍵で署名されています。"
                if public_proof.get("signature_algorithm") == "PS256"
                else "署名情報を利用できません。"
            )
        ),
        "check_rows": _check_rows(verification.get("checks")),
        "warning_rows": _warning_rows(verification.get("warnings")),
        "qr_markup": qr_markup,
    }
    return template.safe_substitute(values)


def load_verification_css() -> str:
    return (_WEB_ROOT / "verify.css").read_text(encoding="utf-8")
