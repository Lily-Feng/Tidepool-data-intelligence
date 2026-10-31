"""Client-side limits for free-tier model quotas: requests per minute and per day.

Clock and sleep are injected so tests run instantly. Counters are per process;
with more than one Cloud Run instance the daily counter moves to Firestore
(Phase 2). Server-side 429s remain the final authority either way.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from support.ports.llm import Priority

# The Gemini API's daily quotas reset at midnight Pacific time.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")

Clock = Callable[[], float]
Sleep = Callable[[float], None]


class RateLimiter:
    """Sliding 60-second window. `acquire` blocks until a request may start."""

    def __init__(self, rpm: int, clock: Clock = time.monotonic, sleep: Sleep = time.sleep):
        if rpm < 1:
            raise ValueError("rpm must be >= 1")
        self.rpm = rpm
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()

    def acquire(self) -> float:
        """Return the seconds waited."""
        waited = 0.0
        while True:
            now = self._clock()
            while self._starts and now - self._starts[0] >= 60.0:
                self._starts.popleft()
            if len(self._starts) < self.rpm:
                self._starts.append(now)
                return waited
            delay = 60.0 - (now - self._starts[0])
            self._sleep(delay)
            waited += delay


class DailyBudget:
    """Requests per quota day. Batch callers (evals) stop `reserve` requests early."""

    def __init__(self, rpd: int, reserve: int = 0, wall_clock: Callable[[], datetime] | None = None):
        if not 0 <= reserve < rpd:
            raise ValueError("reserve must be >= 0 and < rpd")
        self.rpd = rpd
        self.reserve = reserve
        self._now = wall_clock or (lambda: datetime.now(timezone.utc))
        self._day = self._quota_day()
        self.used = 0

    def _quota_day(self):
        return self._now().astimezone(QUOTA_TZ).date()

    def _roll(self) -> None:
        day = self._quota_day()
        if day != self._day:
            self._day, self.used = day, 0

    def remaining(self, priority: Priority = Priority.INTERACTIVE) -> int:
        self._roll()
        limit = self.rpd if priority is Priority.INTERACTIVE else self.rpd - self.reserve
        return max(0, limit - self.used)

    def try_consume(self, priority: Priority = Priority.INTERACTIVE) -> bool:
        if self.remaining(priority) <= 0:
            return False
        self.used += 1
        return True

    def exhaust(self) -> None:
        """The server says the day's quota is gone; stop sending until reset."""
        self._roll()
        self.used = self.rpd
