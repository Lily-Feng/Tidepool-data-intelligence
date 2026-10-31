import json

import pytest

from support.adapters.local.llm import ReplayLLM, ReplayMiss, ScriptedLLM
from support.ports.llm import LLMError, LLMRequest, LLMResponse, Message, Priority


def req(text="hi", **kw):
    return LLMRequest(role="agent", system="s", messages=(Message("user", text),), **kw)


def test_cache_key_ignores_metadata_and_priority():
    a = req(metadata={"run_id": "1"})
    b = req(metadata={"run_id": "2"}, priority=Priority.BATCH)
    assert a.cache_key() == b.cache_key()
    assert a.cache_key() != req("other").cache_key()


def test_scripted_queue_and_function():
    s = ScriptedLLM(["one", LLMResponse(text="two", model_id="x")])
    assert s.generate(req()).text == "one"
    assert s.generate(req()).model_id == "x"
    with pytest.raises(LLMError):
        s.generate(req())
    f = ScriptedLLM(lambda r: r.messages[-1].text.upper())
    assert f.generate(req("abc")).text == "ABC"
    assert len(f.calls) == 1


def test_replay_records_then_replays(tmp_path):
    path = tmp_path / "rec.jsonl"
    inner = ScriptedLLM(['{"category": "upload_failed"}'])
    rec = ReplayLLM(path, "record", inner=inner)
    assert rec.generate(req()).json() == {"category": "upload_failed"}
    assert rec.generate(req()).text  # second call is served from memory, not inner
    assert len(inner.calls) == 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["role"] == "agent"

    replay = ReplayLLM(path, "replay")
    assert replay.generate(req()).json() == {"category": "upload_failed"}
    with pytest.raises(ReplayMiss):
        replay.generate(req("never recorded"))


def test_replay_mode_validation(tmp_path):
    with pytest.raises(ValueError):
        ReplayLLM(tmp_path / "x.jsonl", "record")
    with pytest.raises(ValueError):
        ReplayLLM(tmp_path / "x.jsonl", "live")
