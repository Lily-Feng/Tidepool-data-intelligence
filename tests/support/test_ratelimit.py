from datetime import datetime, timedelta, timezone

import pytest

from support.core.ratelimit import DailyBudget, RateLimiter
from support.ports.llm import Priority


def test_rate_limiter_allows_rpm_then_waits(fake_time):
    rl = RateLimiter(3, fake_time.clock, fake_time.sleep)
    assert [rl.acquire() for _ in range(3)] == [0, 0, 0]
    assert rl.acquire() == pytest.approx(60.0)
    assert fake_time.slept == [pytest.approx(60.0)]


def test_rate_limiter_window_slides(fake_time):
    rl = RateLimiter(2, fake_time.clock, fake_time.sleep)
    rl.acquire()
    fake_time.t = 30
    rl.acquire()
    fake_time.t = 61  # first start has left the window, second has not
    assert rl.acquire() == 0
    assert rl.acquire() == pytest.approx(29.0)


def test_rate_limiter_rejects_zero():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_budget_reserve_blocks_batch_but_not_interactive(wall_clock):
    b = DailyBudget(rpd=5, reserve=2, wall_clock=wall_clock)
    assert all(b.try_consume(Priority.BATCH) for _ in range(3))
    assert not b.try_consume(Priority.BATCH)
    assert b.try_consume(Priority.INTERACTIVE)
    assert b.try_consume(Priority.INTERACTIVE)
    assert not b.try_consume(Priority.INTERACTIVE)


def test_budget_resets_at_pacific_midnight(wall_clock):
    # 2026-10-30 18:00 UTC is 11:00 PDT; reset happens at 07:00 UTC next day.
    b = DailyBudget(rpd=1, wall_clock=wall_clock)
    assert b.try_consume()
    wall_clock.now = datetime(2026, 10, 31, 6, 59, tzinfo=timezone.utc)
    assert not b.try_consume()
    wall_clock.now += timedelta(minutes=2)
    assert b.try_consume()


def test_budget_exhaust(wall_clock):
    b = DailyBudget(rpd=10, wall_clock=wall_clock)
    b.exhaust()
    assert b.remaining() == 0


@pytest.mark.parametrize("rpd,reserve", [(5, 5), (5, -1)])
def test_budget_rejects_bad_reserve(rpd, reserve):
    with pytest.raises(ValueError):
        DailyBudget(rpd, reserve)
