"""Polite, process-local rate limiter for outbound HTTP providers."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Token-window limiter: at most ``calls_per_minute`` plus a min interval.

    Defaults stay under typical free-tier caps (Finnhub ~60/min). Shared
    across threads in one process; not distributed.
    """

    def __init__(
        self,
        calls_per_minute: float = 50.0,
        min_interval: float = 0.2,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if calls_per_minute <= 0:
            raise ValueError("calls_per_minute must be positive")
        self.calls_per_minute = float(calls_per_minute)
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._lock = threading.Lock()
        self._window: deque[float] = deque()
        self._last: float | None = None

    def wait(self) -> None:
        """Block until the next call is allowed."""
        while True:
            delay = 0.0
            with self._lock:
                now = self._clock()
                horizon = now - 60.0
                while self._window and self._window[0] <= horizon:
                    self._window.popleft()

                if self._last is not None:
                    since = now - self._last
                    if since < self.min_interval:
                        delay = max(delay, self.min_interval - since)

                capacity = int(self.calls_per_minute)
                if len(self._window) >= max(capacity, 1):
                    delay = max(delay, 60.0 - (now - self._window[0]) + 0.001)

                if delay <= 0:
                    stamped = self._clock()
                    self._window.append(stamped)
                    self._last = stamped
                    return
            self._sleep(delay)

    def __enter__(self) -> RateLimiter:
        self.wait()
        return self

    def __exit__(self, *exc: object) -> None:
        return None
