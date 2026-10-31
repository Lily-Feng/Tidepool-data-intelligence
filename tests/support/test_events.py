import json

import pytest

from support.adapters.local.events import InProcessPublisher
from support.ports.events import CloudEvent


def ev(**kw):
    base = dict(type="tidy.ticket.created", source="/tidy/tickets", data={"key": "SUP-1"},
                subject="SUP-1")
    return CloudEvent(**{**base, **kw})


def test_cloudevent_json_roundtrip():
    e = ev()
    body = json.loads(e.to_json())
    assert body["specversion"] == "1.0"
    assert body["datacontenttype"] == "application/json"
    assert CloudEvent.from_json(e.to_json()) == e


@pytest.mark.parametrize("kw", [{"type": "ticket.created"}, {"source": "tidy"}])
def test_cloudevent_validation(kw):
    with pytest.raises(ValueError):
        ev(**kw)


def test_from_json_rejects_other_spec():
    body = json.loads(ev().to_json())
    body["specversion"] = "0.3"
    with pytest.raises(ValueError):
        CloudEvent.from_json(json.dumps(body))


def test_in_process_delivery_exact_and_wildcard():
    pub = InProcessPublisher()
    exact, every = [], []
    pub.subscribe("tidy.ticket.created", exact.append)
    pub.subscribe("*", every.append)
    pub.publish(ev())
    pub.publish(ev(type="tidy.ticket.transitioned"))
    assert [e.type for e in exact] == ["tidy.ticket.created"]
    assert len(every) == 2 and len(pub.published) == 2


def test_in_process_rejects_unserialisable_payload():
    with pytest.raises(TypeError):
        InProcessPublisher().publish(ev(data={"when": object()}))
