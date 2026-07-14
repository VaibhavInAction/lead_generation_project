"""Source registry + SOURCES_ENABLED kill switch (README §6, §12)."""

from __future__ import annotations

import pytest

from leadforge.config.settings import Settings
from leadforge.scrapers.intent.fetchers import (
    BraveSearchFetcher,
    DuckDuckGoHtmlFetcher,
    SerperSearchFetcher,
)
from leadforge.scrapers.intent.linkedin_posts import LinkedInPostsScraper
from leadforge.scrapers.registry import (
    _build_search_fetcher,
    enabled_sources,
    get_scraper,
    is_enabled,
    known_sources,
)


def _settings(sources: str = "linkedin_posts", **overrides: object) -> Settings:
    # API keys for the keyed engines so building a scraper works (Serper is default).
    params: dict[str, object] = {"serper_api_key": "test-key", "brave_api_key": "test-key"}
    params.update(overrides)
    return Settings(_env_file=None, sources_enabled=sources, **params)


def test_known_sources_includes_linkedin_posts() -> None:
    assert "linkedin_posts" in known_sources()


def test_enabled_sources_filters_by_config() -> None:
    assert enabled_sources(_settings("linkedin_posts")) == ["linkedin_posts"]
    assert enabled_sources(_settings("reddit")) == []


def test_is_enabled() -> None:
    assert is_enabled("linkedin_posts", _settings("linkedin_posts")) is True
    assert is_enabled("linkedin_posts", _settings("reddit")) is False
    assert is_enabled("nope", _settings("nope")) is False


def test_get_scraper_builds_enabled_source() -> None:
    scraper = get_scraper("linkedin_posts", _settings("linkedin_posts"))
    assert isinstance(scraper, LinkedInPostsScraper)
    assert scraper.source_name == "linkedin_posts"


def test_get_scraper_rejects_unknown_source() -> None:
    with pytest.raises(KeyError):
        get_scraper("mystery", _settings("mystery"))


def test_get_scraper_blocks_disabled_source() -> None:
    with pytest.raises(PermissionError, match="disabled"):
        get_scraper("linkedin_posts", _settings("reddit"))


class TestSearchEngineSelection:
    def test_default_engine_is_serper(self) -> None:
        assert isinstance(_build_search_fetcher(_settings()), SerperSearchFetcher)

    def test_brave_engine_selected(self) -> None:
        fetcher = _build_search_fetcher(_settings(search_engine="brave"))
        assert isinstance(fetcher, BraveSearchFetcher)

    def test_ddg_engine_selected(self) -> None:
        fetcher = _build_search_fetcher(_settings(search_engine="ddg"))
        assert isinstance(fetcher, DuckDuckGoHtmlFetcher)

    def test_serper_without_key_raises(self) -> None:
        with pytest.raises(ValueError, match="SERPER_API_KEY"):
            _build_search_fetcher(
                Settings(_env_file=None, search_engine="serper", serper_api_key="")
            )

    def test_brave_without_key_raises(self) -> None:
        with pytest.raises(ValueError, match="BRAVE_API_KEY"):
            _build_search_fetcher(Settings(_env_file=None, search_engine="brave", brave_api_key=""))

    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown SEARCH_ENGINE"):
            _build_search_fetcher(_settings(search_engine="google"))
