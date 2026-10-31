"""Secret Manager adapter. The Cloud Run identity needs secretAccessor on each secret."""

from __future__ import annotations

from typing import Any

from support.ports.secrets import SecretNotFound


class SecretManagerSecrets:
    def __init__(self, project: str, client: Any = None):
        if client is None:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
        self._client = client
        self.project = project

    @classmethod
    def from_config(cls, section: dict, target) -> "SecretManagerSecrets":
        return cls(section["project"])

    def get(self, name: str) -> str:
        path = f"projects/{self.project}/secrets/{name}/versions/latest"
        try:
            resp = self._client.access_secret_version(name=path)
        except Exception as exc:
            if type(exc).__name__ in ("NotFound", "PermissionDenied"):
                raise SecretNotFound(f"secret {name!r}: {type(exc).__name__}") from exc
            raise
        return resp.payload.data.decode("utf-8")
