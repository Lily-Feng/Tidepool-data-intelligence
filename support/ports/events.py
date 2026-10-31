"""Event port. Every event is a CloudEvents 1.0 JSON envelope, so any broker works.

Delivery to consumers is adapter-specific (Pub/Sub push to HTTP, SQS poller,
in-process handler); the port covers publishing only.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

SPEC_VERSION = "1.0"
TYPE_PREFIX = "tidy."


@dataclass(frozen=True)
class CloudEvent:
    type: str  # e.g. "tidy.ticket.created"
    source: str  # e.g. "/tidy/tickets"
    data: dict
    subject: str | None = None  # e.g. ticket key
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.type.startswith(TYPE_PREFIX):
            raise ValueError(f"event type must start with {TYPE_PREFIX!r}: {self.type!r}")
        if not self.source.startswith("/"):
            raise ValueError(f"event source must be a path: {self.source!r}")

    def to_json(self) -> str:
        body = {
            "specversion": SPEC_VERSION,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time,
            "datacontenttype": "application/json",
            "data": self.data,
        }
        if self.subject is not None:
            body["subject"] = self.subject
        return json.dumps(body, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "CloudEvent":
        body = json.loads(raw)
        if body.get("specversion") != SPEC_VERSION:
            raise ValueError(f"unsupported specversion: {body.get('specversion')!r}")
        return cls(
            type=body["type"],
            source=body["source"],
            data=body.get("data") or {},
            subject=body.get("subject"),
            id=body["id"],
            time=body["time"],
        )


class EventPublisher(Protocol):
    def publish(self, event: CloudEvent) -> str:
        """Publish and return the broker's message ID."""
        ...
