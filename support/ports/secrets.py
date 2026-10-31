"""Secrets port. Values are never logged, printed or written to disk by Tidy."""

from __future__ import annotations

from typing import Protocol


class SecretNotFound(KeyError):
    pass


class Secrets(Protocol):
    def get(self, name: str) -> str: ...
