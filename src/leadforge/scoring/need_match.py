"""Need-match scoring — how well a post fits what the agency sells (README §14).

The scraper already tags each lead with the ``need_category`` (the ``--need``
term from ``needs.yaml`` that surfaced the post, e.g. "marketing agency"). This
scores the *strength* of that fit against the post body: a verbatim phrase match
beats scattered word matches, and an explicit solicitation ("looking for a
marketing agency") beats a passing mention. Transparent keyword matching — no ML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from leadforge.scoring.config import ScoringConfig

# Words too generic to count as evidence the need is present.
_STOPWORDS = frozenset({"a", "an", "the", "for", "of", "and", "to", "in"})

# Explicit "I am shopping for this" phrasing — lifts a match from topical to intent.
_SOLICITATION = re.compile(
    r"\b(?:looking for|look for|searching for|in search of|need(?:ed)?|want|"
    r"seeking|recommend|recommendations?|anyone know|can anyone|hire|hiring|"
    r"outsource|help with|who (?:can|do you)|any (?:recommendations|suggestions))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NeedMatchResult:
    """A 0–100 fit score plus how the need term matched the post."""

    score: int
    full_phrase: bool
    matched_tokens: int
    total_tokens: int
    solicited: bool


def _tokens(need: str) -> list[str]:
    """Content words of the need phrase, lowercased, stopwords dropped."""
    words = re.findall(r"[a-z0-9]+", need.lower())
    content = [w for w in words if w not in _STOPWORDS]
    return content or words  # if the need was *all* stopwords, keep them


def need_match_score(
    *, need_category: str | None, post_text: str | None, config: ScoringConfig
) -> NeedMatchResult:
    """Score topical + intent fit of ``post_text`` against the ``need_category``."""
    need = (need_category or "").strip()
    text = (post_text or "").lower()
    tokens = _tokens(need)
    total = len(tokens)

    if not need or total == 0 or not text:
        return NeedMatchResult(
            score=0, full_phrase=False, matched_tokens=0, total_tokens=total, solicited=False
        )

    full_phrase = need.lower() in text
    matched = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", text))

    if full_phrase:
        base = config.need_full_phrase
    elif matched == total:
        base = config.need_all_tokens
    elif matched > 0:
        base = config.need_partial_cap * (matched / total)
    else:
        base = config.need_topic_floor

    # A solicitation only counts when the need is actually on the page — otherwise
    # "looking for … <something unrelated>" would wrongly inflate a tangential post.
    solicited = bool(_SOLICITATION.search(text)) and matched > 0
    if solicited:
        bonus = (
            config.need_solicitation_bonus
            if base >= config.need_all_tokens
            else (config.need_solicitation_bonus / 2)
        )
    else:
        bonus = 0.0

    score = max(0, min(100, round(base + bonus)))
    return NeedMatchResult(
        score=score,
        full_phrase=full_phrase,
        matched_tokens=matched,
        total_tokens=total,
        solicited=solicited,
    )
