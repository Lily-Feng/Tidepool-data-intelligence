import sys
from types import SimpleNamespace

import pytest

from support.adapters.gcp.secret_manager import SecretManagerSecrets
from support.adapters.local.secrets import EnvSecrets, KeychainSecrets, env_name
from support.ports.secrets import SecretNotFound


def test_env_secrets(monkeypatch):
    assert env_name("gemini-api-key") == "TIDY_SECRET_GEMINI_API_KEY"
    monkeypatch.setenv("TIDY_SECRET_GEMINI_API_KEY", "synthetic-value")
    assert EnvSecrets().get("gemini-api-key") == "synthetic-value"
    monkeypatch.delenv("TIDY_SECRET_GEMINI_API_KEY")
    with pytest.raises(SecretNotFound):
        EnvSecrets().get("gemini-api-key")


def test_keychain_secrets(monkeypatch):
    store = {("tidy", "gemini-api-key"): "synthetic-value"}
    fake = SimpleNamespace(get_password=lambda svc, acct: store.get((svc, acct)))
    monkeypatch.setitem(sys.modules, "keyring", fake)
    k = KeychainSecrets()
    assert k.get("gemini-api-key") == "synthetic-value"
    with pytest.raises(SecretNotFound):
        k.get("other")


class NotFound(Exception):
    pass


class FakeSecretClient:
    def __init__(self, values):
        self.values = values
        self.paths = []

    def access_secret_version(self, name):
        self.paths.append(name)
        if name not in self.values:
            raise NotFound(name)
        return SimpleNamespace(payload=SimpleNamespace(data=self.values[name].encode()))


def test_secret_manager():
    path = "projects/synthetic-project/secrets/gemini-api-key/versions/latest"
    client = FakeSecretClient({path: "synthetic-value"})
    s = SecretManagerSecrets("synthetic-project", client=client)
    assert s.get("gemini-api-key") == "synthetic-value"
    with pytest.raises(SecretNotFound):
        s.get("missing")
