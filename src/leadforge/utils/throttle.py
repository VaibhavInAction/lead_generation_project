"""Rate-limiting primitives — mandatory, not optional (README §6).

Two independent controls compose in the scraper framework:

* :class:`DomainThrottle` — a randomized human-speed delay between requests to the
  same domain (``SCRAPE_DELAY_MIN``/``MAX``).
* :class:`DailyRequestCap` — a hard ceiling on requests per source per day
  (``SCRAPE_DAILY_CAP``).

Both take injected ``sleep``/``rand`` callables so tests run instantly and
deterministically without real waiting (README §23).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Protocol


class Throttle(Protocol):
    """Anything that can enforce a delay before hitting a domain.

    Lets callers (the runner, the scraper's discover phase) accept either a real
    :class:`DomainThrottle` or a test spy without importing the concrete class.
    """

    def wait(self, domain: str) -> float: ...


class DomainThrottle:
    """Enforce a randomized minimum gap between requests to the same domain."""

    def __init__(
        self,
        min_seconds: float,
        max_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if min_seconds > max_seconds:
            raise ValueError("min_seconds must be <= max_seconds")
        self._min = min_seconds
        self._max = max_seconds
        self._sleep = sleep
        self._rand = rand
        self._last_call: dict[str, float] = {}
        self._clock = time.monotonic

    def wait(self, domain: str) -> float:
        """Block until this domain may be hit again; return the seconds waited."""
        target_gap = self._rand(self._min, self._max)
        last = self._last_call.get(domain)
        now = self._clock()
        waited = 0.0
        if last is not None:
            elapsed = now - last
            remaining = target_gap - elapsed
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining
        self._last_call[domain] = self._clock()
        return waited


class DailyRequestCap:
    """A hard per-run ceiling on requests, seeded with today's prior usage.

    ``already_used`` lets the caller carry over requests already spent earlier
    the same day (summed from ``scrape_runs``), so the cap is genuinely daily and
    not merely per-run (README §6).
    """

    def __init__(self, limit: int, *, already_used: int = 0) -> None:
        self.limit = limit
        self.used = already_used

    @property
    def remaining(self) -> int:
        """Requests still allowed today (never negative)."""
        return max(0, self.limit - self.used)

    def allow(self) -> bool:
        """Consume one request if any remain; return whether it was allowed."""
        if self.remaining <= 0:
            return False
        self.used += 1
        return True
