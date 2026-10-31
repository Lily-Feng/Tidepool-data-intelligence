"""Local secrets: environment variables (CI, containers) or macOS Keychain (your Mac)."""

from __future__ import annotations

import os

from support.ports.secrets import SecretNotFound

KEYCHAIN_SERVICE = "tidy"


def env_name(secret: str) -> str:
    """`gemini-api-key` -> `TIDY_SECRET_GEMINI_API_KEY`."""
    return "TIDY_SECRET_" + secret.upper().replace("-", "_")


class EnvSecrets:
    @classmethod
    def from_config(cls, section: dict, target) -> "EnvSecrets":
        return cls()

    def get(self, name: str) -> str:
        value = os.environ.get(env_name(name))
        if not value:
            raise SecretNotFound(f"{env_name(name)} is not set")
        return value


class KeychainSecrets:
    """Reads Keychain item service=`tidy`, account=<secret name>.

    Store a value with:  python -m keyring set tidy gemini-api-key
    """

    def __init__(self, service: str = KEYCHAIN_SERVICE):
        import keyring  # imported lazily so tests need not install it

        self._keyring = keyring
        self.service = service

    @classmethod
    def from_config(cls, section: dict, target) -> "KeychainSecrets":
        return cls(section.get("service", KEYCHAIN_SERVICE))

    def get(self, name: str) -> str:
        value = self._keyring.get_password(self.service, name)
        if not value:
            raise SecretNotFound(f"Keychain item {self.service}/{name} not found")
        return value
