"""Contract every LLM adapter must meet. New adapters (Vertex, Bedrock, Azure)
join the `llm` fixture and must pass unchanged."""

import pytest

from conftest import FakeGenAIClient, fake_response
from support.adapters.gcp.gemini import GeminiLLM, ModelLimits
from support.adapters.local.llm import ReplayLLM, ScriptedLLM
from support.ports.llm import LLMRequest, LLMResponse, Message

REQUEST = LLMRequest(role="agent", system="You are Tidy.",
                     messages=(Message("user", "Is the service up?"),),
                     metadata={"ticket_key": "SUP-1"})


def _scripted(tmp_path, fake_time):
    return ScriptedLLM(["Yes."])


def _replay(tmp_path, fake_time):
    path = tmp_path / "rec.jsonl"
    ReplayLLM(path, "record", inner=ScriptedLLM(["Yes."])).generate(REQUEST)
    return ReplayLLM(path, "replay")


def _gemini(tmp_path, fake_time):
    client = FakeGenAIClient([fake_response("Yes.")])
    return GeminiLLM(client, {"m": ModelLimits(rpm=10, rpd=100)}, {"agent": ("m", None)},
                     clock=fake_time.clock, sleep=fake_time.sleep)


@pytest.fixture(params=[_scripted, _replay, _gemini], ids=["scripted", "replay", "gemini-fake"])
def llm(request, tmp_path, fake_time):
    return request.param(tmp_path, fake_time)


def test_generate_returns_text_and_model(llm):
    r = llm.generate(REQUEST)
    assert isinstance(r, LLMResponse)
    assert r.text == "Yes."
    assert r.model_id


def test_response_tokens_are_non_negative(llm):
    r = llm.generate(REQUEST)
    assert r.input_tokens >= 0 and r.output_tokens >= 0 and r.latency_ms >= 0
