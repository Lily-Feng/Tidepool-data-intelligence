"""In-process event publisher: delivers synchronously to registered handlers."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from support.ports.events import CloudEvent

Handler = Callable[[CloudEvent], None]


class InProcessPublisher:
    def __init__(self):
        self.published: list[CloudEvent] = []
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    @classmethod
    def from_config(cls, section: dict, target) -> "InProcessPublisher":
        return cls()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """`event_type` may be exact (`tidy.ticket.created`) or `*` for everything."""
        self._handlers[event_type].append(handler)

    def publish(self, event: CloudEvent) -> str:
        # Round-trip through JSON so local tests catch payloads a broker would reject.
        event = CloudEvent.from_json(event.to_json())
        self.published.append(event)
        for handler in self._handlers[event.type] + self._handlers["*"]:
            handler(event)
        return event.id
