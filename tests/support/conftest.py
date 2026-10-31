"""Shared fixtures for Tidy tests. Everything runs offline against local adapters.

Tests marked `gcp` call real GCP or Gemini and run only with TIDY_RUN_GCP=1.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "gcp: needs live GCP / Gemini (set TIDY_RUN_GCP=1)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TIDY_RUN_GCP") == "1":
        return
    skip = pytest.mark.skip(reason="live GCP test; set TIDY_RUN_GCP=1")
    for item in items:
        if "gcp" in item.keywords:
            item.add_marker(skip)


class FakeTime:
    """Monotonic clock + sleep that advance instantly."""

    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class FakeWallClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeAPIError(Exception):
    """Shaped like google.genai.errors.APIError: has `.code`, message names the quota."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def per_minute_429():
    return FakeAPIError(429, "RESOURCE_EXHAUSTED quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier")


def per_day_429():
    return FakeAPIError(429, "RESOURCE_EXHAUSTED quotaId=GenerateRequestsPerDayPerProjectPerModel-FreeTier")


def fake_response(text: str, prompt_tokens: int = 5, output_tokens: int = 2):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(prompt_token_count=prompt_tokens,
                                       candidates_token_count=output_tokens,
                                       thoughts_token_count=None),
    )


class FakeGenAIClient:
    """Stand-in for google.genai.Client. `script` items are responses or exceptions."""

    def __init__(self, script=None, models=()):
        self.script = list(script or [])
        self.calls: list[dict] = []
        self._model_list = models
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0) if self.script else fake_response("OK")
        if isinstance(item, Exception):
            raise item
        return item

    def list(self):
        return [SimpleNamespace(name=f"models/{m}", supported_actions=["generateContent"])
                for m in self._model_list]


@pytest.fixture
def fake_time():
    return FakeTime()


@pytest.fixture
def wall_clock():
    return FakeWallClock(datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc))
