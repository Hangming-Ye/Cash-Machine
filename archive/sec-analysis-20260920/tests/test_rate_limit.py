from __future__ import annotations

from sec_analysis.core.rate_limit import RateLimiter


def test_rate_limiter_enforces_min_interval() -> None:
    clock = {"t": 100.0}
    slept: list[float] = []

    def now() -> float:
        return clock["t"]

    def sleep(delay: float) -> None:
        slept.append(delay)
        clock["t"] += delay

    limiter = RateLimiter(calls_per_minute=30, min_interval=0.5, clock=now, sleeper=sleep)
    limiter.wait()
    limiter.wait()
    assert slept == [0.5]


def test_rate_limiter_caps_calls_per_minute() -> None:
    clock = {"t": 0.0}
    slept: list[float] = []

    def now() -> float:
        return clock["t"]

    def sleep(delay: float) -> None:
        slept.append(delay)
        clock["t"] += delay

    limiter = RateLimiter(calls_per_minute=2, min_interval=0, clock=now, sleeper=sleep)
    limiter.wait()
    clock["t"] += 0.01
    limiter.wait()
    clock["t"] += 0.01
    limiter.wait()
    assert slept and slept[-1] > 50
