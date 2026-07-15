"""Combine the signals into a single ``lead_score`` (README §14, §16).

Transparent and rule-based: ``lead_score`` is a configurable weighted blend of
freshness, need-match, and data-quality — *unless* the post is a job posting, in
which case a hard rule slams the score to near-0 no matter how fresh or on-topic
it is. An employer hiring staff is never a client lead, and no amount of recency
should float it to the top of an agency's outreach list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from leadforge.models.enums import PostCategory
from leadforge.scoring.classify import classify_post
from leadforge.scoring.config import ScoringConfig
from leadforge.scoring.freshness import freshness_score
from leadforge.scoring.need_match import need_match_score


@dataclass(frozen=True)
class LeadScoreResult:
    """The final score, the category, and the per-factor breakdown (README §16)."""

    lead_score: int
    category: PostCategory
    freshness: int
    need_match: int
    data_quality: int
    breakdown: dict[str, object]


def score_intent_lead(
    *,
    need_category: str | None,
    post_text: str | None,
    author_name: str | None = None,
    posted_at: datetime | None,
    first_seen: datetime | None,
    data_quality_score: int,
    now: datetime,
    config: ScoringConfig,
) -> LeadScoreResult:
    """Classify, score each factor, and blend into a 0–100 ``lead_score``."""
    classification = classify_post(post_text, author_name=author_name)
    fresh = freshness_score(posted_at=posted_at, first_seen=first_seen, now=now, config=config)
    need = need_match_score(need_category=need_category, post_text=post_text, config=config)
    quality = max(0, min(100, data_quality_score))

    w_fresh, w_need, w_quality = config.normalized_weights()
    blended = w_fresh * fresh.score + w_need * need.score + w_quality * quality

    # Hard rule (README §14): only a genuine client lead earns a real score.
    # Every other category — job posting, recruiter, competitor, noise — is capped
    # near 0 so it can never float above the real leads.
    capped = not classification.category.is_client
    if capped:
        blended = min(blended, config.non_client_score_cap)

    lead_score = max(0, min(100, round(blended)))
    breakdown: dict[str, object] = {
        "category": classification.category.value,
        "freshness": fresh.score,
        "need_match": need.score,
        "data_quality": quality,
        "weights": {"freshness": w_fresh, "need_match": w_need, "data_quality": w_quality},
        "freshness_used_fallback": fresh.used_fallback,
        "non_client_capped": capped,
        "has_request": classification.has_request,
        "signals": classification.signals,
    }
    return LeadScoreResult(
        lead_score=lead_score,
        category=classification.category,
        freshness=fresh.score,
        need_match=need.score,
        data_quality=quality,
        breakdown=breakdown,
    )
