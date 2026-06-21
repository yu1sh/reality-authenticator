"""Canonical JSON serialization used by evidence and proof records."""

from __future__ import annotations

import json


def canonical_json_text(value: object) -> str:
    """Serialize a JSON-compatible value in the project's canonical form."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON-compatible value as canonical UTF-8 bytes."""

    return canonical_json_text(value).encode("utf-8")
