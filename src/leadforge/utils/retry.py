"""Retry with exponential backoff + jitter for transient failures (README §12).

Only the exception types passed in are retried (the framework passes
:class:`~leadforge.scrapers.errors.TransientError`); everything else — blocks,
parse errors — propagates immediately so the caller can react correctly.
``sleep``/``rand`` are injectable for instant, deterministic tests.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_call(
    func: Callable[[], T],
    *,
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[float, float], float] = random.uniform,
) -> T:
    """Call ``func`` up to ``retries`` times, backing off between attempts.

    Delay for attempt *n* (0-indexed) is ``base_delay * 2**n`` capped at
    ``max_delay``, plus up to 50% jitter to avoid synchronized retries. Re-raises
    the last matching exception once attempts are exhausted.
    """
    if retries < 1:
        raise ValueError("retries must be >= 1")

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return func()
        except exceptions as exc:
            last_exc = exc
            if attempt == retries - 1:
                break
            backoff = min(base_delay * (2**attempt), max_delay)
            sleep(backoff + rand(0.0, backoff * 0.5))
    # The loop always ran at least once, so last_exc is set here.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_call exhausted without capturing an exception")  # unreachable
