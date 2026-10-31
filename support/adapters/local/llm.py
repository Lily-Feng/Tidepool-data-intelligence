"""Local LLM adapters: scripted responses for unit tests, record/replay for CI.

CI never calls a live model. `ReplayLLM` in `record` mode wraps a live adapter
and appends each exchange to a JSONL file; in `replay` mode it answers from that
file and fails loudly on a request it has not seen. Recordings hold synthetic
content only, so they can be committed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from support.ports.llm import LLM, LLMError, LLMRequest, LLMResponse

REPO_ROOT = Path(__file__).resolve().parents[3]

Responder = Callable[[LLMRequest], str | LLMResponse]


class ScriptedLLM:
    """Returns queued responses in order, or computes them with a function."""

    def __init__(self, responses: list[str | LLMResponse] | Responder | None = None,
                 model_id: str = "scripted"):
        self._responses = responses if responses is not None else []
        self.model_id = model_id
        self.calls: list[LLMRequest] = []

    @classmethod
    def from_config(cls, section: dict, target) -> "ScriptedLLM":
        return cls(list(section.get("responses", [])), section.get("model_id", "scripted"))

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if callable(self._responses):
            out = self._responses(request)
        elif self._responses:
            out = self._responses.pop(0)
        else:
            raise LLMError("ScriptedLLM has no responses left")
        if isinstance(out, LLMResponse):
            return out
        return LLMResponse(text=out, model_id=self.model_id)


class ReplayMiss(LLMError):
    """Replay mode saw a request with no recording. Re-record against a live model."""


class ReplayLLM:
    def __init__(self, path: Path, mode: str = "replay", inner: LLM | None = None):
        if mode not in ("replay", "record"):
            raise ValueError(f"mode must be replay or record: {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner (live) LLM")
        self.path = path
        self.mode = mode
        self.inner = inner
        self._recorded: dict[str, LLMResponse] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._recorded[row["key"]] = LLMResponse(**row["response"])

    @classmethod
    def from_config(cls, section: dict, target) -> "ReplayLLM":
        path = REPO_ROOT / section["recordings"]
        mode = section.get("mode", "replay")
        inner = None
        if mode == "record":
            from support.core.config import Target
            inner = Target.load(section["inner_target"]).build("llm")
        return cls(path, mode, inner)

    def generate(self, request: LLMRequest) -> LLMResponse:
        key = request.cache_key()
        if key in self._recorded:
            return self._recorded[key]
        if self.mode == "replay":
            raise ReplayMiss(f"no recording for role={request.role!r} key={key[:12]}")
        response = self.inner.generate(request)
        self._recorded[key] = response
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"key": key, "role": request.role,
                                "response": asdict(response)}, sort_keys=True) + "\n")
        return response
