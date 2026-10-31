import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from support.app.main import app

client = TestClient(app)


def test_health(monkeypatch):
    monkeypatch.setenv("TIDY_TARGET", "local")
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["target"] == "local"


def test_ready_local(monkeypatch):
    monkeypatch.setenv("TIDY_TARGET", "local")
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"config": "ok"}


def test_ready_reports_missing_key_without_values(monkeypatch):
    monkeypatch.setenv("TIDY_TARGET", "local-gemini")
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda s, a: None))
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"] == {"config": "ok", "llm_api_key": "missing"}


def test_ready_reports_key_present(monkeypatch):
    monkeypatch.setenv("TIDY_TARGET", "local-gemini")
    monkeypatch.setitem(sys.modules, "keyring",
                        SimpleNamespace(get_password=lambda s, a: "synthetic-value"))
    r = client.get("/ready")
    assert r.status_code == 200
    assert "synthetic-value" not in r.text
