"""LinkedIn public-post miner — the v0.1 core intent source (README §13.1).

`discover()` mines search-engine-indexed *public* posts (never LinkedIn's own
authwalled search); `extract()` renders the public post page and pulls the post
and its author. Both fetchers are injected, so the scraper is exercised entirely
from saved fixtures in tests and never touches the network there (README §23).

Honest expectations (README §13.1): search engines index only a slice of posts
and some authwall anyway — dozens of warm leads per week per niche, not a
firehose. Volume grows by adding phrase templates and niches, never by hammering.
"""

from __future__ import annotations

from collections.abc import Iterator

import structlog

from leadforge.config.settings import Settings
from leadforge.models.schemas import RawLead, SearchQuery
from leadforge.scrapers.base import BaseScraper
from leadforge.scrapers.intent.fetchers import PageFetcher, SearchFetcher
from leadforge.scrapers.intent.parsing import parse_post
from leadforge.scrapers.intent.queries import build_search_terms
from leadforge.utils.throttle import DomainThrottle, Throttle

log = structlog.get_logger("leadforge.scrapers.linkedin_posts")

PLATFORM = "linkedin_public"


class LinkedInPostsScraper(BaseScraper):
    """Mines public LinkedIn posts stating a need, via search-engine discovery."""

    source_name = "linkedin_posts"

    def __init__(
        self,
        settings: Settings,
        *,
        search_fetcher: SearchFetcher,
        page_fetcher: PageFetcher,
        templates: list[str],
        throttle: Throttle | None = None,
    ) -> None:
        self.settings = settings
        self._search = search_fetcher
        self._page = page_fetcher
        self._templates = templates
        # The search phase hits the engine once per phrase template; it must be
        # throttled just like extraction (README §6) or it fires N requests at once.
        self._throttle = throttle or DomainThrottle(
            settings.scrape_delay_min, settings.scrape_delay_max
        )

    def discover(self, query: SearchQuery) -> Iterator[str]:
        """Yield candidate public-post URLs across all phrase templates for the need.

        Each search request is throttled per-engine-domain (README §6), then
        de-duplicated across templates so a post matched by several phrases is
        extracted once. Blocks/timeouts from one search term are logged and
        skipped — one dead search never sinks the run.
        """
        seen: set[str] = set()
        for term in build_search_terms(query.need, self._templates):
            self._throttle.wait(self._search.domain)
            try:
                found = self._search.search(term, query.since)
            except Exception as exc:  # noqa: BLE001 — a failed search term is not fatal
                log.warning("discover.search_failed", term=term, error=str(exc))
                continue
            log.info("discover.search", term=term, results=len(found))
            for post_url in found:
                if post_url not in seen:
                    seen.add(post_url)
                    yield post_url

    def extract(self, url: str) -> RawLead:
        """Render one public post page and return its raw fields as a RawLead.

        Raises :class:`~leadforge.scrapers.errors.BlockedError` /
        ``TransientError`` (from the fetcher) or :class:`ParseError` (from
        parsing) — the framework decides what each means (README §22).
        """
        html = self._page.fetch(url)
        data = parse_post(html, url)
        return RawLead(source=self.source_name, source_url=url, data=data)
