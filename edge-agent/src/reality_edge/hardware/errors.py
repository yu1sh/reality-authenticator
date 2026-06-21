"""Stable hardware capture errors."""

from __future__ import annotations


class HardwareError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

