"""Intent-lead validation + cleaning boundary (README §17).

The single Phase-6 entry point the pipeline calls: it cleans an intent lead's
text/name fields, applies hard rules (empty author or post text after cleaning →
reject), and computes a data-quality score with soft-issue flags. Pure over plain
values — no ORM, no DB — so the service applies the result to the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from leadforge.cleaning.names import clean_author_name
from leadforge.cleaning.text import clean_text
from leadforge.validation.quality import score_intent_lead


class ValidationError(ValueError):
    """A lead failed a hard validation rule and must go to the rejects table."""


@dataclass(frozen=True)
class IntentAssessment:
    """Cleaned fields + quality result, or a hard-reject reason."""

    rejected: bool
    reason: str | None
    author_name: str
    author_headline: str | None
    company: str | None
    need_text: str
    post_text: str
    data_quality_score: int
    quality_flags: list[str]


def _rejected(reason: str) -> IntentAssessment:
    return IntentAssessment(
        rejected=True,
        reason=reason,
        author_name="",
        author_headline=None,
        company=None,
        need_text="",
        post_text="",
        data_quality_score=0,
        quality_flags=[],
    )


def assess_intent_lead(
    *,
    author_name: str | None,
    author_headline: str | None,
    company: str | None,
    need_text: str | None,
    post_text: str | None,
    posted_at: datetime | None,
    author_profile_url: str | None,
) -> IntentAssessment:
    """Clean, hard-validate, and score one intent lead's fields."""
    name = clean_author_name(author_name)
    headline = clean_text(author_headline) or None
    company_clean = clean_text(company) or None
    need_clean = clean_text(need_text)
    post_clean = clean_text(post_text)  # emoji preserved in the post body

    # Hard rules — a lead with no author or no post text is not a lead.
    if not name.value:
        return _rejected("author name empty after cleaning")
    if not post_clean:
        return _rejected("post text empty after cleaning")

    quality = score_intent_lead(
        author_name=name.value,
        author_low_confidence=name.low_confidence,
        author_headline=headline,
        company=company_clean,
        post_text=post_clean,
        posted_at=posted_at,
        author_profile_url=author_profile_url,
    )

    return IntentAssessment(
        rejected=False,
        reason=None,
        author_name=name.value,
        author_headline=headline,
        company=company_clean,
        need_text=need_clean or post_clean,
        post_text=post_clean,
        data_quality_score=quality.score,
        quality_flags=quality.flags,
    )
