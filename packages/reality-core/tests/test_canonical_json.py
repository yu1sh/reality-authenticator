import math

import pytest

from reality_core import canonical_json_bytes, canonical_json_text


def test_key_order_does_not_change_canonical_json() -> None:
    first = {"z": 1, "a": {"b": 2, "a": 1}}
    second = {"a": {"a": 1, "b": 2}, "z": 1}

    assert canonical_json_text(first) == canonical_json_text(second)
    assert canonical_json_text(first) == '{"a":{"a":1,"b":2},"z":1}'


def test_unicode_is_encoded_as_utf8_without_ascii_escaping() -> None:
    value = {"message": "現実証明"}

    assert canonical_json_text(value) == '{"message":"現実証明"}'
    assert canonical_json_bytes(value) == '{"message":"現実証明"}'.encode("utf-8")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_text({"value": value})
