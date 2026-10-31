import pytest

from support.adapters.local.events import InProcessPublisher
from support.adapters.local.llm import ReplayLLM
from support.adapters.local.secrets import EnvSecrets
from support.core.config import ADAPTERS, TARGETS_DIR, ConfigError, Target, _resolve


def write(tmp_path, name, text):
    p = tmp_path / f"{name}.yaml"
    p.write_text(text)
    return p


def test_local_target_builds_every_port():
    t = Target.load("local")
    assert isinstance(t.build("llm"), ReplayLLM)
    assert isinstance(t.build("secrets"), EnvSecrets)
    assert isinstance(t.build("events"), InProcessPublisher)
    assert t.build("events") is t.build("events")  # cached


@pytest.mark.parametrize("path", sorted(TARGETS_DIR.glob("[!_]*.yaml")), ids=lambda p: p.stem)
def test_every_target_parses_and_names_registered_adapters(path, monkeypatch):
    monkeypatch.setenv("TIDY_GCP_PROJECT", "synthetic-project")
    t = Target.load(path.stem)
    for port in ("llm", "secrets", "events"):
        section = t.section(port)
        assert (port, section["adapter"]) in ADAPTERS


def test_every_registered_adapter_resolves():
    for path in ADAPTERS.values():
        assert callable(_resolve(path))


def test_extends_deep_merges(tmp_path):
    write(tmp_path, "base", "llm:\n  adapter: a\n  models: {x: 1, y: 2}\n")
    child = write(tmp_path, "child", "extends: base\nllm:\n  models: {y: 3}\n")
    t = Target.load("child", path=child)
    assert t.section("llm") == {"adapter": "a", "models": {"x": 1, "y": 3}}


def test_env_expansion_is_lazy_and_strict(tmp_path, monkeypatch):
    p = write(tmp_path, "t", "gcp: {project: '${TIDY_TEST_PROJECT}'}\nevents: {adapter: local.in_process}\n")
    monkeypatch.delenv("TIDY_TEST_PROJECT", raising=False)
    t = Target.load("t", path=p)
    t.build("events")  # unaffected by the missing variable
    with pytest.raises(ConfigError, match="TIDY_TEST_PROJECT"):
        t.section("gcp")
    monkeypatch.setenv("TIDY_TEST_PROJECT", "synthetic-project")
    assert t.section("gcp") == {"project": "synthetic-project"}


def test_errors(tmp_path):
    with pytest.raises(ConfigError, match="unknown target"):
        Target.load("does-not-exist")
    t = Target.load("t", path=write(tmp_path, "t", "llm: {adapter: nope}\n"))
    with pytest.raises(ConfigError, match="no adapter"):
        t.build("llm")
    with pytest.raises(ConfigError, match="no 'events' section"):
        t.build("events")


def test_override(tmp_path):
    t = Target.load("local")
    sentinel = object()
    t.override("llm", sentinel)
    assert t.build("llm") is sentinel


def test_target_from_env(monkeypatch):
    monkeypatch.setenv("TIDY_TARGET", "local")
    assert Target.load().name == "local"
