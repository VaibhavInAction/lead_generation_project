"""Network/browser fetchers for the LinkedIn post miner (README §13.1).

Fetching is isolated behind two tiny :class:`typing.Protocol`s so the scraper
can be driven by fakes/fixtures in tests (never the live network, README §23)
and by real clients in production:

* :class:`SearchFetcher` — run one search query and return candidate LinkedIn
  post URLs. Each engine owns its own request-building *and* result-parsing, so
  swapping engines (Serper / Brave / DDG) touches only the injected fetcher (README §7).
* :class:`PageFetcher`    — render a public post page (Playwright, since many
  LinkedIn posts are JS-rendered).

All translate infrastructure failures into the scraper error taxonomy so the
framework can throttle/retry/kill-switch correctly (README §22).
"""

from __future__ import annotations

from typing import Protocol

import httpx
import structlog

from leadforge.config.settings import Settings
from leadforge.scrapers.errors import BlockedError, TransientError
from leadforge.scrapers.intent.parsing import (
    parse_brave_results,
    parse_search_results,
    parse_serper_results,
)
from leadforge.scrapers.intent.queries import brave_freshness, build_search_url, serper_tbs
from leadforge.utils.user_agents import DEFAULT_PROFILE, BrowserProfile

log = structlog.get_logger("leadforge.scrapers.fetchers")

# Final-URL / content markers that mean "logged-out wall" — we stop, never evade.
_AUTHWALL_MARKERS = ("/authwall", "/login", "/uas/login", "authwall")

# Search API endpoints (README §13.1).
_SERPER_ENDPOINT = "https://google.serper.dev/search"
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class SearchFetcher(Protocol):
    """Run one search query and return candidate LinkedIn post URLs."""

    # Host used as the per-domain throttle key for the search phase (README §6).
    domain: str

    def search(self, term: str, since: str) -> list[str]: ...


class PageFetcher(Protocol):
    """Fetch a rendered post page as HTML."""

    def fetch(self, url: str) -> str: ...


class SerperSearchFetcher:
    """Serper.dev fetcher — the default engine: Google results as JSON (README §13.1).

    Free and card-free. Reads the API key from settings (never hardcoded); a
    missing/invalid key maps to :class:`BlockedError` so the run stops with an
    actionable message rather than silently finding nothing.
    """

    domain = "google.serper.dev"

    def __init__(
        self, api_key: str, *, country: str = "us", num: int = 10, timeout: float = 15.0
    ) -> None:
        self._api_key = api_key
        self._country = country
        self._num = num
        self._timeout = timeout

    def search(self, term: str, since: str) -> list[str]:
        """POST ``term`` to the Serper API and return LinkedIn post URLs.

        Body follows Serper's spec: ``q`` + ``gl`` + ``num``, plus ``tbs`` (Google
        ``qdr`` recency) *only* when ``--since`` maps to a window — sending an
        empty/invalid ``tbs`` is what makes Serper reject the request with HTTP 400.
        """
        body: dict[str, str | int] = {"q": term, "gl": self._country, "num": self._num}
        tbs = serper_tbs(since)
        if tbs is not None:
            body["tbs"] = tbs
        headers = {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

        try:
            resp = httpx.post(_SERPER_ENDPOINT, json=body, headers=headers, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise TransientError(f"Serper search timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransientError(f"Serper search request failed: {exc}") from exc

        if resp.status_code != 200:
            # Serper explains 4xx (bad body, out of credits, …) in the JSON body;
            # log it before raising so live failures are diagnosable.
            log.warning("serper.error_response", status=resp.status_code, body=resp.text)
            if resp.status_code in (401, 403):
                raise BlockedError(
                    f"Serper API rejected the key (HTTP {resp.status_code}) — check SERPER_API_KEY"
                )
            if resp.status_code == 429:
                raise BlockedError("Serper API rate limited (HTTP 429)")
            if resp.status_code >= 500:
                raise TransientError(f"Serper API returned {resp.status_code}")
            raise TransientError(f"Serper API returned HTTP {resp.status_code}")

        return parse_serper_results(resp.json())


class BraveSearchFetcher:
    """Brave Search API fetcher — a robust JSON engine, but the key needs a card (README §13.1).

    Reads the API key from settings (never hardcoded); a missing/invalid key maps
    to :class:`BlockedError` so the run stops with an actionable message rather
    than silently finding nothing.
    """

    domain = "api.search.brave.com"

    def __init__(self, api_key: str, *, count: int = 20, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._count = count
        self._timeout = timeout

    def search(self, term: str, since: str) -> list[str]:
        """Query the Brave API for ``term`` and return LinkedIn post URLs."""
        params: dict[str, str | int] = {"q": term, "count": self._count}
        freshness = brave_freshness(since)
        if freshness is not None:
            params["freshness"] = freshness
        headers = {"Accept": "application/json", "X-Subscription-Token": self._api_key}

        try:
            resp = httpx.get(_BRAVE_ENDPOINT, params=params, headers=headers, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise TransientError(f"Brave search timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransientError(f"Brave search request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            raise BlockedError(
                f"Brave API rejected the key (HTTP {resp.status_code}) — check BRAVE_API_KEY"
            )
        if resp.status_code == 429:
            raise BlockedError("Brave API rate limited (HTTP 429)")
        if resp.status_code >= 500:
            raise TransientError(f"Brave API returned {resp.status_code}")
        if resp.status_code != 200:
            raise TransientError(f"Brave API returned unexpected {resp.status_code}")

        return parse_brave_results(resp.json())


class DuckDuckGoHtmlFetcher:
    """Fallback fetcher scraping DuckDuckGo's HTML endpoint.

    Not the default: DDG soft-blocks automated HTML requests with HTTP 202, so it
    is unreliable — kept only as a keyless fallback (README §13.1).
    """

    domain = "html.duckduckgo.com"

    def __init__(self, profile: BrowserProfile = DEFAULT_PROFILE, *, timeout: float = 15.0) -> None:
        self._headers = {"User-Agent": profile.user_agent, "Accept-Language": profile.locale}
        self._timeout = timeout

    def search(self, term: str, since: str) -> list[str]:
        """GET the DDG HTML results for ``term`` and return LinkedIn post URLs."""
        url = build_search_url(term, since)
        try:
            resp = httpx.get(
                url, headers=self._headers, timeout=self._timeout, follow_redirects=True
            )
        except httpx.TimeoutException as exc:
            raise TransientError(f"search timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransientError(f"search request failed: {exc}") from exc

        # 202 is DDG's soft block for automated HTML requests (README §13.1).
        if resp.status_code in (202, 403, 429):
            raise BlockedError(f"DuckDuckGo returned {resp.status_code} (soft-blocked)")
        if resp.status_code >= 500:
            raise TransientError(f"search engine returned {resp.status_code}")
        return parse_search_results(resp.text)


class PlaywrightPageFetcher:
    """Playwright-backed fetcher for public post pages (logged out, no evasion)."""

    def __init__(self, settings: Settings, profile: BrowserProfile = DEFAULT_PROFILE) -> None:
        self._headless = settings.scrape_headless
        self._profile = profile

    def fetch(self, url: str) -> str:
        """Open ``url`` in a headless browser and return the rendered HTML.

        A redirect to an authwall/login raises :class:`BlockedError` — the run's
        kill switch takes over from there (README §13). Import is local so the
        rest of the package loads without Playwright present.
        """
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=self._headless)
                try:
                    context = browser.new_context(
                        user_agent=self._profile.user_agent,
                        # BrowserProfile.viewport is a {"width","height"} dict; Playwright
                        # types it as a TypedDict, so the shape matches at runtime.
                        viewport=self._profile.viewport,  # type: ignore[arg-type]
                        locale=self._profile.locale,
                    )
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    final_url = (page.url or "").lower()
                    if any(marker in final_url for marker in _AUTHWALL_MARKERS):
                        raise BlockedError(f"authwall/login redirect: {page.url}")
                    return page.content()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            # Timeouts and navigation errors are transient; let the framework retry.
            raise TransientError(f"browser fetch failed: {exc}") from exc
