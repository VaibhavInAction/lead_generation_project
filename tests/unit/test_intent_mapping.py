"""RawLead → IntentLead mapping at the scraper boundary (README §7, §14)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from leadforge.models.schemas import RawLead
from leadforge.scrapers.intent.mapping import (
    MappingError,
    company_from_headline,
    raw_to_intent_lead,
)


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("Founder at Acme Studios", "Acme Studios"),
        ("CEO @ Acme", "Acme"),
        ("Head of Growth at Bright Labs", "Bright Labs"),
        ("Freelance designer", None),
        (None, None),
    ],
)
def test_company_from_headline(headline: str | None, expected: str | None) -> None:
    assert company_from_headline(headline) == expected


def _raw(**data: object) -> RawLead:
    base: dict[str, object] = {
        "author_name": "Jane Doe",
        "author_headline": "Founder at Acme Studios",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe",
        "post_text": "We are looking for a marketing agency in Mumbai.",
        "posted_at": datetime(2026, 7, 10, tzinfo=UTC),
    }
    base.update(data)
    return RawLead(source="linkedin_posts", source_url="https://x/posts/1", data=base)


def test_maps_expected_fields() -> None:
    lead = raw_to_intent_lead(_raw(), need_category="marketing")
    assert lead.author_name == "Jane Doe"
    assert lead.company == "Acme Studios"
    assert lead.need_category == "marketing"
    assert lead.post_url == "https://x/posts/1"
    assert lead.platform == "linkedin_public"
    assert lead.posted_at == datetime(2026, 7, 10, tzinfo=UTC)
    # Scoring is Phase 9: the mapper leaves freshness/lifecycle unset, so the DB
    # default (0 / new) applies on insert and re-scrapes never clobber them.
    assert lead.freshness_score is None


def test_missing_author_raises_mapping_error() -> None:
    with pytest.raises(MappingError, match="missing"):
        raw_to_intent_lead(_raw(author_name=""), need_category="marketing")


def test_missing_post_text_raises_mapping_error() -> None:
    with pytest.raises(MappingError):
        raw_to_intent_lead(_raw(post_text=None), need_category="marketing")


def test_non_datetime_posted_at_is_dropped() -> None:
    lead = raw_to_intent_lead(_raw(posted_at="4 days ago"), need_category="marketing")
    assert lead.posted_at is None
