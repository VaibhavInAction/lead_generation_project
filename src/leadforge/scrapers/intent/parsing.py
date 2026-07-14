"""Result parsing for intent mining (README §13.1).

Pure functions, deliberately free of any network or browser dependency so they
are tested against saved fixtures (README §23):

* :func:`parse_serper_results` — pull candidate LinkedIn post URLs out of a
  Serper.dev (Google) API JSON payload.
* :func:`parse_brave_results` — pull candidate LinkedIn post URLs out of a Brave
  Search API JSON payload.
* :func:`parse_search_results` — pull candidate LinkedIn post URLs out of a
  DuckDuckGo HTML results page (unwrapping DDG's redirect links).
* :func:`parse_post` — pull post text, author, headline, and timestamp out of a
  public LinkedIn post page. The author comes from the URL slug (or an og:description
  ``"<Name> on LinkedIn: …"`` prefix when present), *not* og:title — which is the
  post body. Raises :class:`ParseError` when required fields are missing, and
  :class:`BlockedError` when the page is LinkedIn's logged-out sign-up wall rather
  than a real post, so the framework skips it instead of storing it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from leadforge.scrapers.errors import BlockedError, ParseError

# A public LinkedIn post lives at /posts/... or /feed/update/... — company and
# profile pages are deliberately excluded here (this source mines posts only).
_POST_URL_RE = re.compile(r"linkedin\.com/(posts|feed/update)/", re.IGNORECASE)


def _keep_post_urls(candidates: list[str]) -> list[str]:
    """Filter to LinkedIn post URLs, strip query strings, and de-dupe in order."""
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not _POST_URL_RE.search(candidate):
            continue
        clean = candidate.split("?", 1)[0]  # stable dedup key, no tracking params
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def parse_brave_results(payload: dict[str, Any]) -> list[str]:
    """Return de-duplicated LinkedIn post URLs from a Brave Search API response.

    Reads ``payload["web"]["results"][*]["url"]`` and keeps only post URLs.
    Order is preserved (search rank); a malformed payload yields an empty list
    rather than raising — one bad search term never sinks the run (README §22).
    """
    web = payload.get("web")
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return []
    candidates = [
        item["url"]
        for item in results
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    return _keep_post_urls(candidates)


def parse_serper_results(payload: dict[str, Any]) -> list[str]:
    """Return de-duplicated LinkedIn post URLs from a Serper.dev (Google) response.

    Reads ``payload["organic"][*]["link"]`` and keeps only post URLs. Order is
    preserved (search rank); a malformed payload yields an empty list rather than
    raising — one bad search term never sinks the run (README §22).
    """
    organic = payload.get("organic")
    if not isinstance(organic, list):
        return []
    candidates = [
        item["link"]
        for item in organic
        if isinstance(item, dict) and isinstance(item.get("link"), str)
    ]
    return _keep_post_urls(candidates)


def _unwrap_ddg(href: str) -> str:
    """Resolve a DuckDuckGo redirect (``/l/?uddg=<encoded>``) to its target URL."""
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        query = urlsplit(href).query
        target = parse_qs(query).get("uddg")
        if target:
            return unquote(target[0])
    if href.startswith("//"):
        return f"https:{href}"
    return href


def parse_search_results(html: str) -> list[str]:
    """Return de-duplicated LinkedIn post URLs from a DDG HTML results page.

    Order is preserved (search rank); non-LinkedIn and non-post links are dropped.
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []
    for anchor in soup.select("a.result__a, a.result__url, a[href]"):
        raw_href = anchor.get("href")
        if isinstance(raw_href, str) and raw_href:
            candidates.append(_unwrap_ddg(raw_href))
    return _keep_post_urls(candidates)


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    """Content of a ``<meta property=...>`` / ``<meta name=...>`` tag, if present."""
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    if isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


_ON_LINKEDIN_RE = re.compile(r"\s+on\s+LinkedIn\b", re.IGNORECASE)

# Strong, wall-specific markers that a "/posts/" page is actually LinkedIn's
# logged-out sign-up wall, not a real post (README §13).
_AUTHWALL_MARKERS = (
    "sign up | linkedin",
    "500 million+ members",
    "manage your professional identity",
    "join linkedin to",
    "agree & join linkedin",
)


def is_authwall(soup: BeautifulSoup) -> bool:
    """True when the page is LinkedIn's logged-out sign-up wall rather than a post.

    Checks page content (title + og metadata), not just the final URL — a
    ``/posts/`` URL can still serve the wall.
    """
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    parts = (title, _meta(soup, "og:title") or "", _meta(soup, "og:description") or "")
    haystack = " ".join(parts).lower()
    return any(marker in haystack for marker in _AUTHWALL_MARKERS)


def _split_on_linkedin(text: str) -> tuple[str | None, str | None]:
    """Split ``"<Name> on LinkedIn: <body>"`` into ``(name, body)``; ``(None, None)`` otherwise."""
    match = _ON_LINKEDIN_RE.search(text)
    if not match:
        return None, None
    name = text[: match.start()].strip()
    body = text[match.end() :].lstrip(" :–—-").strip()
    return (name or None, body or None)


def _looks_like_name(candidate: str) -> bool:
    """Cheap sanity check that a parsed author string is a name, not a sentence."""
    return 1 <= len(candidate) <= 60 and candidate.count(" ") <= 6


def _author_from_slug(url: str) -> str | None:
    """Derive an author name from a post URL slug: ``/posts/<author-slug>_<activity>``.

    Trailing numeric member IDs are dropped, hyphens become spaces, and each word
    is title-cased — e.g. ``paul-mccarron-79785053`` → ``"Paul Mccarron"``.
    """
    match = re.search(r"/posts/([^/?#]+)", urlsplit(url).path)
    if not match:
        return None
    slug = match.group(1).split("_", 1)[0]
    parts = [p for p in slug.split("-") if p]
    # Drop trailing LinkedIn ID tokens — any token containing a digit
    # (e.g. "79785053" or the hex-ish "8aa8977"); real name parts are alphabetic.
    while parts and any(ch.isdigit() for ch in parts[-1]):
        parts.pop()
    if not parts:
        return None
    return " ".join(part.capitalize() for part in parts)


def _first_profile_url(soup: BeautifulSoup) -> str | None:
    """First ``/in/<slug>`` profile link on the page, absolutized to https."""
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if isinstance(href, str) and "/in/" in href:
            if href.startswith("//"):
                return f"https:{href}"
            if href.startswith("/"):
                return f"https://www.linkedin.com{href}"
            if href.startswith("http"):
                return href.split("?", 1)[0]
    return None


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing ``Z``), else ``None``."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_date_published(node: object) -> Iterator[str]:
    """Yield every ``datePublished`` string found anywhere in a JSON-LD structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "datePublished" and isinstance(value, str):
                yield value
            else:
                yield from _find_date_published(value)
    elif isinstance(node, list):
        for item in node:
            yield from _find_date_published(item)


def _posted_at(soup: BeautifulSoup) -> datetime | None:
    """Best-effort post timestamp; ``None`` when genuinely absent.

    Prefers JSON-LD ``datePublished`` (what real LinkedIn post pages expose),
    falling back to a ``<time datetime="...">`` element.
    """
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for value in _find_date_published(data):
            parsed = _parse_iso(value)
            if parsed is not None:
                return parsed

    tag = soup.find("time")
    if isinstance(tag, Tag):
        datetime_attr = tag.get("datetime")
        if isinstance(datetime_attr, str):
            return _parse_iso(datetime_attr)
    return None


def parse_post(html: str, url: str) -> dict[str, object]:
    """Extract post + author fields from a public LinkedIn post page.

    Author resolution (README §13.1): og:title is the *post body*, not the author,
    so the author is taken from a clean ``"<Name> on LinkedIn: …"`` og:description
    prefix when present, otherwise derived from the URL slug. The post text goes to
    ``post_text``, never ``author_name``.

    Raises :class:`BlockedError` if the page is the logged-out sign-up wall, and
    :class:`ParseError` (carrying the HTML for snapshotting) when required fields
    — an author and post text — cannot be found.
    """
    soup = BeautifulSoup(html, "lxml")

    if is_authwall(soup):
        raise BlockedError(f"logged-out sign-up wall served instead of a post: {url}")

    description = _meta(soup, "og:description")
    title = _meta(soup, "og:title")
    desc_name, desc_body = _split_on_linkedin(description) if description else (None, None)

    # Post text is the body — after stripping an "on LinkedIn:" wrapper if present.
    post_text = desc_body or description or title
    if post_text is None:
        article = soup.find("article") or soup.find("main")
        if isinstance(article, Tag):
            post_text = article.get_text(" ", strip=True) or None

    # Author: a clean name from og:description wins; otherwise the URL slug.
    author_name = desc_name if desc_name and _looks_like_name(desc_name) else None
    if author_name is None:
        author_name = _author_from_slug(url)

    if not author_name or not post_text:
        raise ParseError(
            "could not extract author/post_text from post page",
            url=url,
            html=html,
        )

    headline_tag = soup.select_one(".author-headline, [data-test-id='author-headline']")
    author_headline = headline_tag.get_text(strip=True) if isinstance(headline_tag, Tag) else None

    return {
        "author_name": author_name,
        "author_headline": author_headline,
        "author_profile_url": _first_profile_url(soup),
        "post_text": post_text,
        "posted_at": _posted_at(soup),
    }
