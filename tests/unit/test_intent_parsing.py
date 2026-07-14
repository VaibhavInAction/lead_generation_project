"""Offline parsing of DDG results and LinkedIn post pages (README §13.1, §23)."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from leadforge.scrapers.errors import BlockedError, ParseError
from leadforge.scrapers.intent.parsing import (
    _author_from_slug,
    parse_brave_results,
    parse_post,
    parse_search_results,
    parse_serper_results,
)

JANE = "https://www.linkedin.com/posts/jane-doe_marketing-activity-111"
RAVI = "https://www.linkedin.com/posts/ravi-kumar_need-marketing-activity-222"


class TestParseSerperResults:
    def test_extracts_deduped_post_urls(self, serper_json: str) -> None:
        urls = parse_serper_results(json.loads(serper_json))
        assert urls == [JANE, RAVI]

    def test_filters_non_post_and_non_linkedin(self, serper_json: str) -> None:
        urls = parse_serper_results(json.loads(serper_json))
        assert all("linkedin.com/posts" in u for u in urls)
        assert not any("example.com" in u for u in urls)
        assert not any("/company/" in u for u in urls)

    @pytest.mark.parametrize(
        "payload",
        [{}, {"organic": "nope"}, {"organic": [{"no_link": 1}]}],
    )
    def test_malformed_payload_yields_empty(self, payload: dict) -> None:
        assert parse_serper_results(payload) == []


class TestParseBraveResults:
    def test_extracts_deduped_post_urls(self, brave_json: str) -> None:
        urls = parse_brave_results(json.loads(brave_json))
        assert urls == [JANE, RAVI]

    def test_filters_non_post_and_non_linkedin(self, brave_json: str) -> None:
        urls = parse_brave_results(json.loads(brave_json))
        assert all("linkedin.com/posts" in u for u in urls)
        assert not any("example.com" in u for u in urls)
        assert not any("/company/" in u for u in urls)

    @pytest.mark.parametrize(
        "payload",
        [{}, {"web": {}}, {"web": {"results": "nope"}}, {"web": {"results": [{"no_url": 1}]}}],
    )
    def test_malformed_payload_yields_empty(self, payload: dict) -> None:
        assert parse_brave_results(payload) == []


class TestParseSearchResults:
    def test_extracts_deduped_linkedin_post_urls(self, ddg_html: str) -> None:
        urls = parse_search_results(ddg_html)
        assert urls == [
            "https://www.linkedin.com/posts/jane-doe_marketing-help-activity-111",
            "https://www.linkedin.com/posts/ravi-kumar_need-marketing-activity-222",
        ]

    def test_filters_non_post_and_non_linkedin(self, ddg_html: str) -> None:
        urls = parse_search_results(ddg_html)
        assert all("linkedin.com/posts" in u for u in urls)
        assert not any("example.com" in u for u in urls)
        assert not any("/company/" in u for u in urls)


class TestAuthorFromSlug:
    @pytest.mark.parametrize(
        ("url", "name"),
        [
            ("https://www.linkedin.com/posts/sarah-udaipurwala_x-activity-1", "Sarah Udaipurwala"),
            ("https://www.linkedin.com/posts/paul-mccarron-79785053_y-activity-2", "Paul Mccarron"),
            ("https://www.linkedin.com/posts/aleea-khan-8aa8977_h-activity-9", "Aleea Khan"),
            ("https://www.linkedin.com/posts/amandaglandon_z-activity-3", "Amandaglandon"),
            ("https://www.linkedin.com/posts/jbeat_activity-4", "Jbeat"),
        ],
    )
    def test_derives_name_from_slug(self, url: str, name: str) -> None:
        assert _author_from_slug(url) == name


class TestParsePost:
    def test_extracts_expected_fields_time_fallback(self, post_html: str) -> None:
        # og:description has no "on LinkedIn" prefix -> author comes from the slug;
        # posted_at falls back to <time datetime>.
        data = parse_post(post_html, "https://www.linkedin.com/posts/jane-doe_111")
        assert data["author_name"] == "Jane Doe"  # from slug, not the post body
        assert data["author_headline"] == "Founder at Acme Studios"
        assert data["author_profile_url"] == "https://www.linkedin.com/in/jane-doe"
        assert isinstance(data["post_text"], str)
        assert "marketing agency" in data["post_text"]
        assert data["posted_at"] == datetime.fromisoformat("2026-07-10T09:30:00+00:00")

    def test_author_from_description_and_jsonld_date(self, hiring_post_html: str) -> None:
        url = "https://www.linkedin.com/posts/paul-mccarron-79785053_were-hiring-activity-333"
        data = parse_post(hiring_post_html, url)
        # og:description "<Name> on LinkedIn: ..." wins over the slug ("Paul Mccarron").
        assert data["author_name"] == "Paul McCarron"
        # Post body goes to post_text, with the "on LinkedIn:" wrapper stripped.
        assert "Marketing Manager" in data["post_text"]
        assert "on LinkedIn" not in data["post_text"]
        # posted_at comes from JSON-LD datePublished.
        assert data["posted_at"] == datetime.fromisoformat("2026-07-11T14:22:00+00:00")
        assert data["author_profile_url"] == "https://www.linkedin.com/in/paul-mccarron-79785053"

    def test_author_from_slug_when_description_is_body(self, slug_post_html: str) -> None:
        url = "https://www.linkedin.com/posts/sarah-udaipurwala_activity-999"
        data = parse_post(slug_post_html, url)
        assert data["author_name"] == "Sarah Udaipurwala"  # derived from the slug
        assert "SUM Consulting" in data["post_text"]
        assert data["author_name"] not in data["post_text"]  # name is not the body
        assert data["posted_at"] is None  # gracefully NULL when genuinely absent
        assert data["author_profile_url"] is None

    def test_authwall_page_raises_blocked_error(self, authwall_html: str) -> None:
        url = "https://www.linkedin.com/posts/jbeat_im-hiring-activity-555"
        with pytest.raises(BlockedError):
            parse_post(authwall_html, url)

    def test_raises_parse_error_with_html_on_bad_layout(self, broken_post_html: str) -> None:
        url = "https://www.linkedin.com/posts/broken_1"
        with pytest.raises(ParseError) as exc_info:
            parse_post(broken_post_html, url)
        # The HTML rides along so the framework can snapshot it (README §22).
        assert exc_info.value.url == url
        assert exc_info.value.html == broken_post_html
