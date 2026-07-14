"""RawLead → IntentLead mapping (README §7, §14).

The type boundary between the *dumb* scraper output and a persisted record. This
is a minimal, honest map: required fields are enforced, the company name is
lifted from the author's headline, and everything else is carried through.

Deliberately out of scope here (later phases): field normalization/validation
(Phase 6), author→company *website* resolution (Phase 8), and freshness/lead
scoring (Phase 9) — so ``freshness_score`` is left at its default 0.
"""

from __future__ import annotations

import re

from leadforge.models.orm import IntentLead
from leadforge.models.schemas import RawLead

# "Founder at Acme Studios" / "CEO @ Acme" → "Acme Studios" / "Acme".
# `at` needs word boundaries; `@` (not a word char) must not require one.
_COMPANY_RE = re.compile(r"(?:\bat\b|@)\s+(.+?)\s*$", re.IGNORECASE)

_MAX_NEED_TEXT = 500


class MappingError(ValueError):
    """A RawLead is missing fields required to form an IntentLead."""


def company_from_headline(headline: str | None) -> str | None:
    """Best-effort company name from a headline; ``None`` if not expressed."""
    if not headline:
        return None
    match = _COMPANY_RE.search(headline)
    return match.group(1).strip() if match else None


def raw_to_intent_lead(raw: RawLead, *, need_category: str) -> IntentLead:
    """Build a (transient) :class:`IntentLead` from a scraped :class:`RawLead`.

    ``need_category`` is the taxonomy key for the run (the ``--need`` value).
    Raises :class:`MappingError` if the raw record lacks an author or post text.
    """
    data = raw.data
    author_name = str(data.get("author_name") or "").strip()
    post_text = str(data.get("post_text") or "").strip()
    if not author_name or not post_text:
        raise MappingError(f"missing author_name/post_text for {raw.source_url}")

    headline = _opt_str(data.get("author_headline"))
    posted_at = data.get("posted_at")

    return IntentLead(
        author_name=author_name,
        author_profile_url=_opt_str(data.get("author_profile_url")),
        author_headline=headline,
        company=company_from_headline(headline),
        need_text=post_text[:_MAX_NEED_TEXT],
        need_category=need_category,
        post_url=raw.source_url,
        post_text=post_text,
        posted_at=posted_at if _is_datetime(posted_at) else None,
        platform=str(data.get("platform") or "linkedin_public"),
        # freshness_score stays at its default 0 — scoring is Phase 9.
    )


def _opt_str(value: object) -> str | None:
    """Coerce a present, non-empty value to ``str``; otherwise ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_datetime(value: object) -> bool:
    from datetime import datetime

    return isinstance(value, datetime)
