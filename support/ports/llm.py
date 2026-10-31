"""LLM port: one text-or-JSON generation call, addressed by logical role.

Callers name a role (`agent`, `support`, `judge`), never a model ID. The target
config maps roles to models, limits and fallbacks, so changing models is a
config change. Tool calling is added with the agent in Phase 4.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Protocol


class Priority(str, Enum):
    """Interactive work may use the reserved slice of the daily quota; batch may not."""

    INTERACTIVE = "interactive"
    BATCH = "batch"


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "model"
    text: str


@dataclass(frozen=True)
class LLMRequest:
    role: str
    system: str
    messages: tuple[Message, ...]
    response_schema: dict | None = None  # JSON Schema; output is JSON when set
    temperature: float = 0.0
    max_output_tokens: int = 1024
    priority: Priority = Priority.INTERACTIVE
    # Trace context (ticket_key, prompt_version, run_id). Not part of the cache key.
    metadata: dict[str, str] = field(default_factory=dict)

    def cache_key(self) -> str:
        """Stable hash of everything that affects the output, used by replay."""
        body = asdict(self)
        body.pop("metadata")
        body.pop("priority")
        raw = json.dumps(body, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    latency_ms: int = 0

    def json(self) -> dict:
        return json.loads(self.text)


class LLMError(RuntimeError):
    """The model call failed for a reason other than quota."""


class QuotaExhausted(LLMError):
    """Every model allowed for the role is out of quota. Callers hand off, never guess."""


class LLM(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...
