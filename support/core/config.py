"""Target configuration: which adapter backs each port, and its settings.

A target is a YAML file in support/targets/. `${VAR}` placeholders are expanded
from the environment, so project IDs and other identifiers never live in the
repo. Adapters are resolved by name from a registry of import paths, so a cloud
SDK is imported only when its adapter is selected.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Any

import yaml

TARGETS_DIR = Path(__file__).resolve().parents[1] / "targets"
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")

# (port, adapter name) -> "module:factory". A factory takes (section, target).
ADAPTERS: dict[tuple[str, str], str] = {
    ("llm", "local.scripted"): "support.adapters.local.llm:ScriptedLLM.from_config",
    ("llm", "local.replay"): "support.adapters.local.llm:ReplayLLM.from_config",
    ("llm", "gcp.gemini"): "support.adapters.gcp.gemini:GeminiLLM.from_config",
    ("secrets", "local.env"): "support.adapters.local.secrets:EnvSecrets.from_config",
    ("secrets", "local.keychain"): "support.adapters.local.secrets:KeychainSecrets.from_config",
    ("secrets", "gcp.secret_manager"): "support.adapters.gcp.secret_manager:SecretManagerSecrets.from_config",
    ("events", "local.in_process"): "support.adapters.local.events:InProcessPublisher.from_config",
}


class ConfigError(ValueError):
    pass


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ConfigError(f"environment variable {name} is not set")
            return os.environ[name]
        return _ENV_REF.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read(path: Path) -> dict:
    """Read a target file, applying `extends: <name>` (deep merge, child wins)."""
    raw = yaml.safe_load(path.read_text()) or {}
    parent = raw.pop("extends", None)
    if parent:
        raw = _merge(_read(path.parent / f"{parent}.yaml"), raw)
    return raw


def _resolve(path: str):
    module_name, _, attr_path = path.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


class Target:
    """A loaded target. `build(port)` constructs and caches that port's adapter."""

    def __init__(self, name: str, raw: dict):
        self.name = name
        self._raw = raw
        self._built: dict[str, Any] = {}

    @classmethod
    def load(cls, name: str | None = None, path: Path | None = None) -> "Target":
        name = name or os.environ.get("TIDY_TARGET", "local")
        path = path or TARGETS_DIR / f"{name}.yaml"
        if not path.exists():
            raise ConfigError(f"unknown target {name!r}: {path} not found")
        return cls(name, _read(path))

    def section(self, port: str) -> dict:
        if port not in self._raw:
            raise ConfigError(f"target {self.name!r} has no {port!r} section")
        # Expanded lazily so a missing env var only matters for ports in use.
        return _expand(self._raw[port])

    def build(self, port: str) -> Any:
        if port not in self._built:
            section = self.section(port)
            adapter = section.get("adapter")
            key = (port, adapter)
            if key not in ADAPTERS:
                raise ConfigError(f"no adapter {adapter!r} registered for port {port!r}")
            self._built[port] = _resolve(ADAPTERS[key])(section, self)
        return self._built[port]

    def override(self, port: str, adapter: Any) -> None:
        """Inject a ready-made adapter (tests, scripts)."""
        self._built[port] = adapter
