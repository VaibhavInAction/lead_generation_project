"""Scraper error taxonomy (README §22).

The pipeline must survive constant scraper failure, so failures are typed by how
the framework should react:

* :class:`TransientError` — timeout / 5xx → retry with backoff.
* :class:`BlockedError`   — authwall / 403 / CAPTCHA → stop and log, never evade;
  N consecutive ones abort the run (kill switch, README §6, §13).
* :class:`ParseError`     — page layout changed → snapshot the HTML, log, skip.

``ValidationError`` (RawLead → typed record) belongs to the validation layer
(Phase 6) and is intentionally not defined here.
"""

from __future__ import annotations


class ScraperError(Exception):
    """Base class for all scraper failures."""


class TransientError(ScraperError):
    """A retryable failure (timeout, connection reset, 5xx)."""


class BlockedError(ScraperError):
    """A hard block: authwall, 403, or CAPTCHA. Never evaded — stop and report."""


class ParseError(ScraperError):
    """A page could not be parsed. Carries the offending HTML for snapshotting."""

    def __init__(self, message: str, *, url: str, html: str | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.html = html
