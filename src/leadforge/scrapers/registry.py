"""Config-driven source registry (README §7, §12).

Adding a source is one entry here plus its scraper module — no other code
changes. ``SOURCES_ENABLED`` is the kill switch (README §6): a disabled source
cannot be built, so a single config line takes any source (including LinkedIn)
fully offline.
"""

from __future__ import annotations

from collections.abc import Callable

from leadforge.config.settings import Settings
from leadforge.scrapers.base import BaseScraper
from leadforge.scrapers.intent.fetchers import (
    BraveSearchFetcher,
    DuckDuckGoHtmlFetcher,
    PlaywrightPageFetcher,
    SearchFetcher,
    SerperSearchFetcher,
)
from leadforge.scrapers.intent.linkedin_posts import LinkedInPostsScraper
from leadforge.scrapers.intent.queries import load_query_templates

# A factory builds a ready-to-run scraper (with real fetchers) from settings.
ScraperFactory = Callable[[Settings], BaseScraper]


def _build_search_fetcher(settings: Settings) -> SearchFetcher:
    """Select the discovery engine from ``SEARCH_ENGINE`` (README §13.1).

    Serper is the default; Brave is an alternative JSON engine; DDG is a keyless
    fallback. Raises ``ValueError`` for an unknown engine or a keyed engine
    selected with its API key unset.
    """
    engine = settings.search_engine.strip().lower()
    if engine == "serper":
        if not settings.serper_api_key:
            raise ValueError(
                "SEARCH_ENGINE=serper requires SERPER_API_KEY — set it in .env "
                "(free key, no card, at https://serper.dev) or use SEARCH_ENGINE=ddg"
            )
        return SerperSearchFetcher(settings.serper_api_key, country=settings.search_country)
    if engine == "brave":
        if not settings.brave_api_key:
            raise ValueError(
                "SEARCH_ENGINE=brave requires BRAVE_API_KEY — set it in .env "
                "(key at https://brave.com/search/api/) or use SEARCH_ENGINE=serper"
            )
        return BraveSearchFetcher(settings.brave_api_key)
    if engine in ("ddg", "duckduckgo"):
        return DuckDuckGoHtmlFetcher()
    raise ValueError(
        f"unknown SEARCH_ENGINE {settings.search_engine!r} (use 'serper', 'brave', or 'ddg')"
    )


def _build_linkedin_posts(settings: Settings) -> BaseScraper:
    """Wire the LinkedIn post miner with its configured search + Playwright fetchers."""
    templates = load_query_templates(settings.intent_queries_path)
    return LinkedInPostsScraper(
        settings,
        search_fetcher=_build_search_fetcher(settings),
        page_fetcher=PlaywrightPageFetcher(settings),
        templates=templates,
    )


# The one place a source name maps to its implementation (README §12).
_REGISTRY: dict[str, ScraperFactory] = {
    "linkedin_posts": _build_linkedin_posts,
}


def known_sources() -> list[str]:
    """All source names the codebase can build, regardless of enablement."""
    return sorted(_REGISTRY)


def enabled_sources(settings: Settings) -> list[str]:
    """Source names both known and switched on via ``SOURCES_ENABLED``."""
    return [name for name in settings.sources if name in _REGISTRY]


def is_enabled(name: str, settings: Settings) -> bool:
    """Whether ``name`` is a known source and enabled in config."""
    return name in _REGISTRY and name in settings.sources


def get_scraper(name: str, settings: Settings) -> BaseScraper:
    """Build the scraper for ``name``.

    Raises ``KeyError`` for an unknown source and ``PermissionError`` for a known
    source disabled via ``SOURCES_ENABLED`` (the compliance kill switch, README §6).
    """
    if name not in _REGISTRY:
        raise KeyError(f"unknown source {name!r}; known: {known_sources()}")
    if name not in settings.sources:
        raise PermissionError(
            f"source {name!r} is disabled — add it to SOURCES_ENABLED to enable it"
        )
    return _REGISTRY[name](settings)
