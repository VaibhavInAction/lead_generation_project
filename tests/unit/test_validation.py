"""Field normalizers, quality scoring, and the intent assessment (README §17, §23)."""

from __future__ import annotations

from datetime import UTC, datetime

import phonenumbers
import pytest

from leadforge.validation.intent import assess_intent_lead
from leadforge.validation.normalizers import (
    is_valid_url,
    normalize_email,
    normalize_phone,
    normalize_url,
    registered_domain,
)
from leadforge.validation.quality import score_intent_lead


class TestNormalizers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Person@Example.COM", "person@example.com"),
            ("  a@b.co  ", "a@b.co"),
            ("not-an-email", None),
            ("missing@domain", None),
            (None, None),
        ],
    )
    def test_normalize_email(self, raw: str | None, expected: str | None) -> None:
        assert normalize_email(raw) == expected

    def test_normalize_url_strips_tracking_and_lowercases_host(self) -> None:
        url = "https://Example.com/Path?utm_source=li&id=5&trk=abc#frag"
        assert normalize_url(url) == "https://example.com/Path?id=5"

    @pytest.mark.parametrize("bad", ["not a url", "ftp://x.com", "", None])
    def test_normalize_url_rejects_non_http(self, bad: str | None) -> None:
        assert normalize_url(bad) is None

    @pytest.mark.parametrize(
        ("url", "valid"),
        [("https://x.com", True), ("http://x.com/p", True), ("ftp://x", False), (None, False)],
    )
    def test_is_valid_url(self, url: str | None, valid: bool) -> None:
        assert is_valid_url(url) is valid

    def test_registered_domain(self) -> None:
        assert registered_domain("https://www.example.co.uk/team") == "example.co.uk"
        assert registered_domain("not a url") is None

    def test_normalize_phone_valid(self) -> None:
        example = phonenumbers.example_number("US")  # a guaranteed-valid number
        e164 = phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.E164)
        assert normalize_phone(e164) == e164

    @pytest.mark.parametrize("bad", ["abc", "12", "", None])
    def test_normalize_phone_invalid(self, bad: str | None) -> None:
        assert normalize_phone(bad) is None


class TestQualityScore:
    def test_full_lead_scores_100(self) -> None:
        result = score_intent_lead(
            author_name="Casey Lee",
            author_low_confidence=False,
            author_headline="Founder at Acme",
            company="Acme",
            post_text="We are looking for a marketing agency to help us grow.",
            posted_at=datetime(2026, 7, 8, tzinfo=UTC),
            author_profile_url="https://www.linkedin.com/in/casey-lee",
        )
        assert result.score == 100
        assert result.flags == []

    def test_sparse_lead_scores_low_with_flags(self) -> None:
        result = score_intent_lead(
            author_name="Amandaglandon",
            author_low_confidence=True,
            author_headline=None,
            company=None,
            post_text="hi",
            posted_at=None,
            author_profile_url=None,
        )
        assert result.score == 25  # 15 (low-conf author) + 10 (short post)
        assert "author_name_low_confidence" in result.flags
        assert "post_text_short" in result.flags
        assert "missing_posted_at" in result.flags
        assert "missing_company" in result.flags

    def test_invalid_profile_url_flagged(self) -> None:
        result = score_intent_lead(
            author_name="Casey Lee",
            author_low_confidence=False,
            author_headline="Founder",
            company="Acme",
            post_text="A sufficiently long post about needs.",
            posted_at=datetime(2026, 7, 8, tzinfo=UTC),
            author_profile_url="not-a-url",
        )
        assert "invalid_author_profile_url" in result.flags


class TestAssessIntentLead:
    def test_cleans_fields_and_scores(self) -> None:
        assessment = assess_intent_lead(
            author_name="Aleea Khan 8aa8977",
            author_headline=" Founder &amp; CEO ",
            company="  𝐀𝐜𝐦𝐞  ",
            need_text="💡 We&#39;re hiring",
            post_text="💡 We&#39;re hiring a 𝐦𝐚𝐫𝐤𝐞𝐭𝐢𝐧𝐠 manager for our team",
            posted_at=datetime(2026, 7, 8, tzinfo=UTC),
            author_profile_url="https://www.linkedin.com/in/aleea-khan",
        )
        assert assessment.rejected is False
        assert assessment.author_name == "Aleea Khan"  # ID fragment stripped
        assert assessment.author_headline == "Founder & CEO"  # entity decoded
        assert assessment.company == "Acme"  # math letters folded
        # Emoji preserved in the post body.
        assert assessment.post_text == "💡 We're hiring a marketing manager for our team"
        assert "author_name_low_confidence" not in assessment.quality_flags
        assert assessment.data_quality_score == 100

    def test_empty_author_after_cleaning_rejected(self) -> None:
        assessment = assess_intent_lead(
            author_name="🚀🚀",  # emoji-only -> empty after cleaning
            author_headline=None,
            company=None,
            need_text="post",
            post_text="We are hiring a marketing manager.",
            posted_at=None,
            author_profile_url=None,
        )
        assert assessment.rejected is True
        assert assessment.reason is not None
        assert "author" in assessment.reason

    def test_empty_post_text_rejected(self) -> None:
        assessment = assess_intent_lead(
            author_name="Casey Lee",
            author_headline=None,
            company=None,
            need_text="",
            post_text="   ",  # whitespace-only -> empty after cleaning
            posted_at=None,
            author_profile_url=None,
        )
        assert assessment.rejected is True
        assert "post text" in (assessment.reason or "")
