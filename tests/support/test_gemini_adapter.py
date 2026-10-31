"""Quota behaviour of the Gemini adapter, against a fake client (no network)."""

import pytest

from conftest import FakeAPIError, FakeGenAIClient, fake_response, per_day_429, per_minute_429
from support.adapters.gcp.gemini import GeminiLLM, ModelLimits
from support.ports.llm import LLMError, LLMRequest, Message, Priority, QuotaExhausted

MODELS = {"lite": ModelLimits(rpm=2, rpd=5, reserve=2), "lite-old": ModelLimits(rpm=2, rpd=5)}
ROLES = {"agent": ("lite", "lite-old"), "judge": ("lite-old", None)}


def make(fake_time, wall_clock, script=(), **kw):
    client = FakeGenAIClient(list(script))
    llm = GeminiLLM(client, MODELS, ROLES, clock=fake_time.clock, sleep=fake_time.sleep,
                    wall_clock=wall_clock, **kw)
    return llm, client


def req(role="agent", priority=Priority.INTERACTIVE, schema=None):
    return LLMRequest(role=role, system="sys", messages=(Message("user", "q"),),
                      priority=priority, response_schema=schema)


def test_request_shape(fake_time, wall_clock):
    llm, client = make(fake_time, wall_clock)
    llm.generate(req(schema={"type": "object"}))
    call = client.calls[0]
    assert call["model"] == "lite"
    assert call["contents"] == [{"role": "user", "parts": [{"text": "q"}]}]
    assert call["config"]["system_instruction"] == "sys"
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_json_schema"] == {"type": "object"}


def test_response_mapping(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock, [fake_response("hi", 7, 3)])
    r = llm.generate(req())
    assert (r.text, r.model_id, r.input_tokens, r.output_tokens, r.finish_reason) == \
           ("hi", "lite", 7, 3, "stop")


def test_rpm_limiter_spaces_calls(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock)
    for _ in range(3):
        llm.generate(req())
    assert fake_time.slept == [pytest.approx(60.0)]


def test_per_minute_429_retries_same_model(fake_time, wall_clock):
    llm, client = make(fake_time, wall_clock, [per_minute_429(), fake_response("ok")])
    assert llm.generate(req()).model_id == "lite"
    assert [c["model"] for c in client.calls] == ["lite", "lite"]
    assert 5.0 in fake_time.slept


def test_repeated_429_falls_back(fake_time, wall_clock):
    llm, client = make(fake_time, wall_clock,
                       [per_minute_429(), per_minute_429(), per_minute_429(), fake_response("ok")])
    r = llm.generate(req())
    assert r.model_id == "lite-old"
    assert llm.budgets["lite"].remaining() > 0  # per-minute limits do not burn the day


def test_per_day_429_exhausts_model_and_falls_back(fake_time, wall_clock):
    llm, client = make(fake_time, wall_clock, [per_day_429(), fake_response("ok")])
    assert llm.generate(req()).model_id == "lite-old"
    assert llm.budgets["lite"].remaining() == 0
    llm.generate(req())
    assert client.calls[-1]["model"] == "lite-old"  # exhausted model is skipped


def test_batch_cannot_use_reserve(fake_time, wall_clock):
    llm, client = make(fake_time, wall_clock)
    for _ in range(3):  # rpd 5, reserve 2 -> 3 batch calls on primary
        llm.generate(req(priority=Priority.BATCH))
    assert llm.generate(req(priority=Priority.BATCH)).model_id == "lite-old"
    assert llm.generate(req(priority=Priority.INTERACTIVE)).model_id == "lite"


def test_quota_exhausted_when_all_models_out(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock, [per_day_429()])
    with pytest.raises(QuotaExhausted):
        llm.generate(req(role="judge"))


def test_other_errors_raise_llm_error(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock, [FakeAPIError(400, "bad request")])
    with pytest.raises(LLMError) as e:
        llm.generate(req())
    assert not isinstance(e.value, QuotaExhausted)


def test_empty_response_is_an_error(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock, [fake_response("")])
    with pytest.raises(LLMError, match="empty response"):
        llm.generate(req())


def test_unknown_role_and_unconfigured_model(fake_time, wall_clock):
    llm, _ = make(fake_time, wall_clock)
    with pytest.raises(LLMError):
        llm.generate(req(role="nope"))
    with pytest.raises(ValueError):
        GeminiLLM(FakeGenAIClient(), MODELS, {"agent": ("missing", None)})


def test_list_models(fake_time, wall_clock):
    llm = GeminiLLM(FakeGenAIClient(models=["lite"]), MODELS, ROLES)
    assert llm.list_models() == [("models/lite", ["generateContent"])]


@pytest.mark.gcp
def test_live_gemini_probe():
    """One real call per configured agent role. Uses 1 request of daily quota."""
    from support.core.config import Target

    r = Target.load("local-gemini").build("llm").generate(
        LLMRequest(role="agent", system="Connectivity check.",
                   messages=(Message("user", "Reply with OK."),), max_output_tokens=16))
    assert r.text.strip()


def test_real_sdk_429_shape_is_recognised(fake_time, wall_clock):
    errors = pytest.importorskip("google.genai.errors")
    daily = errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded",
        "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    llm, _ = make(fake_time, wall_clock, [daily, fake_response("ok")])
    assert llm.generate(req()).model_id == "lite-old"
    assert llm.budgets["lite"].remaining() == 0
