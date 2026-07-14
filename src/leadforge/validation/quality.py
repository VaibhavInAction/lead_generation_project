"""Data-quality scoring for intent leads (README §10, §14, §17).

Transparent, weighted completeness + validity → 0–100, plus human-readable flags
for the soft issues that lowered the score. No black boxes: the weights are right
here and sum to 100.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from leadforge.validation.normalizers import is_valid_url

# Per-factor weights (sum = 100). Completeness + validity of the fields that make
# an intent lead actionable (README §14).
_W_AUTHOR = 25
_W_AUTHOR_LOW_CONF = 15  # present but we don't fully trust the name
_W_POST_TEXT = 25
_W_POST_TEXT_SHORT = 10
_W_POSTED_AT = 15
_W_PROFILE_URL = 15
_W_PROFILE_URL_INVALID = 5
_W_HEADLINE = 10
_W_COMPANY = 10

_MIN_POST_TEXT_LEN = 20


@dataclass
class QualityResult:
    """A 0–100 quality score and the flags explaining any deductions."""

    score: int
    flags: list[str]


def score_intent_lead(
    *,
    author_name: str | None,
    author_low_confidence: bool,
    author_headline: str | None,
    company: str | None,
    post_text: str | None,
    posted_at: datetime | None,
    author_profile_url: str | None,
) -> QualityResult:
    """Score an intent lead's completeness + validity, returning score and flags."""
    score = 0
    flags: list[str] = []

    if author_name:
        if author_low_confidence:
            score += _W_AUTHOR_LOW_CONF
            flags.append("author_name_low_confidence")
        else:
            score += _W_AUTHOR
    else:
        flags.append("missing_author_name")

    if post_text and len(post_text) >= _MIN_POST_TEXT_LEN:
        score += _W_POST_TEXT
    elif post_text:
        score += _W_POST_TEXT_SHORT
        flags.append("post_text_short")
    else:
        flags.append("missing_post_text")

    if posted_at is not None:
        score += _W_POSTED_AT
    else:
        flags.append("missing_posted_at")

    if author_profile_url:
        if is_valid_url(author_profile_url):
            score += _W_PROFILE_URL
        else:
            score += _W_PROFILE_URL_INVALID
            flags.append("invalid_author_profile_url")
    else:
        flags.append("missing_author_profile_url")

    if author_headline:
        score += _W_HEADLINE
    else:
        flags.append("missing_headline")

    if company:
        score += _W_COMPANY
    else:
        flags.append("missing_company")

    return QualityResult(score=max(0, min(100, score)), flags=flags)
