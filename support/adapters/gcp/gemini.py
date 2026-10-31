"""Gemini API adapter (Google AI Studio key) with free-tier quota handling.

Each logical role maps to a primary model and an optional fallback. Per model,
a client-side limiter keeps under RPM and a daily budget keeps under RPD, with a
reserve that batch work (evals) cannot touch. A per-minute 429 is retried with
backoff; a per-day 429 marks that model exhausted until the Pacific-time reset.
When every model for a role is out, `QuotaExhausted` tells the caller to hand off.

The same `google-genai` client can target Vertex AI later; only `from_config`
changes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from support.core.ratelimit import DailyBudget, RateLimiter
from support.ports.llm import LLMError, LLMRequest, LLMResponse, QuotaExhausted


@dataclass(frozen=True)
class ModelLimits:
    rpm: int
    rpd: int
    reserve: int = 0


class _RateLimited(Exception):
    def __init__(self, model: str, daily: bool):
        super().__init__(model)
        self.daily = daily


def _is_429(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def _is_daily(exc: Exception) -> bool:
    # Quota IDs in the error details name the window, e.g. "...PerDayPerProjectPerModel...".
    return "PerDay" in str(exc)


class GeminiLLM:
    def __init__(self, client: Any, models: dict[str, ModelLimits],
                 roles: dict[str, tuple[str, str | None]], *,
                 clock=time.monotonic, sleep=time.sleep, wall_clock=None,
                 max_retries: int = 2, backoff_s: float = 5.0):
        for role, (primary, fallback) in roles.items():
            for model in (primary, fallback):
                if model is not None and model not in models:
                    raise ValueError(f"role {role!r} uses {model!r}, which has no limits configured")
        self._client = client
        self._roles = roles
        self._clock = clock
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self.limiters = {m: RateLimiter(lim.rpm, clock, sleep) for m, lim in models.items()}
        self.budgets = {m: DailyBudget(lim.rpd, lim.reserve, wall_clock) for m, lim in models.items()}

    @classmethod
    def from_config(cls, section: dict, target) -> "GeminiLLM":
        from google import genai

        api_key = target.build("secrets").get(section["api_key_secret"])
        models = {m: ModelLimits(**lim) for m, lim in section["models"].items()}
        roles = {r: (spec["model"], spec.get("fallback")) for r, spec in section["roles"].items()}
        return cls(genai.Client(api_key=api_key), models, roles)

    def models_for(self, role: str) -> list[str]:
        if role not in self._roles:
            raise LLMError(f"unknown role {role!r}")
        return [m for m in self._roles[role] if m is not None]

    def generate(self, request: LLMRequest) -> LLMResponse:
        for model in self.models_for(request.role):
            try:
                return self.call_model(model, request)
            except QuotaExhausted:
                continue
        raise QuotaExhausted(f"no quota left for role {request.role!r} "
                             f"(priority={request.priority.value})")

    def call_model(self, model: str, request: LLMRequest) -> LLMResponse:
        """One model, no fallback. Used by `generate` and by the limits check."""
        if not self.budgets[model].try_consume(request.priority):
            raise QuotaExhausted(f"{model}: daily budget used")
        try:
            return self._call(model, request)
        except _RateLimited as limited:
            if limited.daily:
                self.budgets[model].exhaust()
            raise QuotaExhausted(f"{model}: rate limited (daily={limited.daily})") from limited

    def _call(self, model: str, request: LLMRequest) -> LLMResponse:
        config: dict[str, Any] = {
            "system_instruction": request.system,
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
        }
        if request.response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = request.response_schema
        contents = [{"role": m.role, "parts": [{"text": m.text}]} for m in request.messages]

        for attempt in range(self._max_retries + 1):
            self.limiters[model].acquire()
            started = self._clock()
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=contents, config=config)
            except Exception as exc:
                if not _is_429(exc):
                    raise LLMError(f"{model}: {type(exc).__name__}: {exc}") from exc
                if _is_daily(exc) or attempt == self._max_retries:
                    raise _RateLimited(model, daily=_is_daily(exc)) from exc
                self._sleep(self._backoff_s * 2 ** attempt)
                continue
            return self._to_response(model, resp, started)
        raise AssertionError("unreachable")

    def _to_response(self, model: str, resp: Any, started: float) -> LLMResponse:
        candidates = getattr(resp, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        finish_reason = getattr(finish, "name", None) or (str(finish) if finish else "unknown")
        if not resp.text:
            raise LLMError(f"{model}: empty response (finish_reason={finish_reason})")
        usage = getattr(resp, "usage_metadata", None)
        output_tokens = (getattr(usage, "candidates_token_count", 0) or 0) + \
                        (getattr(usage, "thoughts_token_count", 0) or 0)
        return LLMResponse(
            text=resp.text,
            model_id=model,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=output_tokens,
            finish_reason=finish_reason.lower(),
            latency_ms=int((self._clock() - started) * 1000),
        )

    def list_models(self) -> list[tuple[str, list[str]]]:
        """(model name, supported actions) for every model the key can see."""
        return [(m.name, list(m.supported_actions or [])) for m in self._client.models.list()]
