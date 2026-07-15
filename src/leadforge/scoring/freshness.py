"""Freshness scoring — intent decays fast (README §14).

A publicly stated need is perishable: "looking for a video editor" is warm today
and dead in a week. We model that with exponential decay on a configurable
half-life (default ~4 days): a brand-new post scores ~100, and the score halves
every half-life. ``posted_at`` is the clock; when it's missing we fall back to
``first_seen`` (always set) with a penalty, because we don't truly know when the
author posted. Missing timestamps never crash — they degrade to a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from leadforge.scoring.config import ScoringConfig

_SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class FreshnessResult:
    """A 0–100 freshness score and whether it used the first_seen fallback."""

    score: int
    used_fallback: bool
    age_days: float


def _as_utc(value: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC.

    SQLite hands back naive datetimes; our provenance clock (utcnow) is aware.
    Treating a naive value as UTC keeps the subtraction from raising and matches
    how every timestamp in this project is actually stored (README §10).
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def freshness_score(
    *,
    posted_at: datetime | None,
    first_seen: datetime | None,
    now: datetime,
    config: ScoringConfig,
) -> FreshnessResult:
    """Score how fresh an intent post is, decaying on the configured half-life.

    Uses ``posted_at`` when present; otherwise ``first_seen`` with a penalty. If
    both are missing (shouldn't happen — first_seen is always set — but old data
    might surprise us), returns 0 rather than crashing.
    """
    reference = posted_at if posted_at is not None else first_seen
    used_fallback = posted_at is None
    if reference is None:
        return FreshnessResult(score=0, used_fallback=True, age_days=0.0)

    now_utc = _as_utc(now)
    delta_seconds = (now_utc - _as_utc(reference)).total_seconds()
    # Clamp future-dated / clock-skewed posts to "brand new" instead of >100.
    age_days = max(0.0, delta_seconds / _SECONDS_PER_DAY)

    half_life = max(config.freshness_half_life_days, 1e-6)  # guard divide-by-zero
    raw = 100.0 * (0.5 ** (age_days / half_life))
    if used_fallback:
        raw *= config.freshness_fallback_penalty

    score = max(0, min(100, round(raw)))
    return FreshnessResult(score=score, used_fallback=used_fallback, age_days=age_days)
