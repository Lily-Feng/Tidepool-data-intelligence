"""Platform-neutral interfaces. Business logic imports these, never an adapter.

Each port gets a local adapter (used by every test) and a GCP adapter. AWS and
Azure equivalents are listed in support/docs/architecture.md. Ports land in the
phase that first needs them; Phase 0 defines LLM, Secrets and EventPublisher.
"""

from support.ports.events import CloudEvent, EventPublisher
from support.ports.llm import (
    LLM,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    Priority,
    QuotaExhausted,
)
from support.ports.secrets import SecretNotFound, Secrets

__all__ = [
    "CloudEvent",
    "EventPublisher",
    "LLM",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "Priority",
    "QuotaExhausted",
    "SecretNotFound",
    "Secrets",
]
