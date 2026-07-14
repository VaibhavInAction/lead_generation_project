"""Scraper framework: the interface every source implements, and the wrapper that
gives every source its non-negotiable cross-cutting behavior (README §12).

A :class:`BaseScraper` is *dumb and source-specific*: it only knows how to
``discover`` candidate URLs and ``extract`` one page into a :class:`RawLead`. It
knows nothing about throttling, retries, checkpoints, or the database (README §9).

:class:`ScrapeRunner` wraps a scraper with the behavior the compliance and
reliability rules demand:

* randomized per-domain throttle + hard daily request cap (README §6),
* retry-with-backoff on transient errors (README §12),
* checkpoint persistence so an interrupted run resumes (``resume=True``),
* the kill switch: N consecutive authwalls/CAPTCHAs abort the run cleanly —
  we stop and report, never evade (README §6, §13),
* snapshot-on-parse-failure and a ``scrape_runs`` audit row per run (README §22).

Persistence collaborators are injected as small :class:`typing.Protocol`s, so the
runner never imports the database and is trivially testable with fakes (README §24).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import structlog

from leadforge.config.settings import Settings
from leadforge.models.schemas import RawLead, SearchQuery
from leadforge.scrapers.errors import BlockedError, ParseError, TransientError
from leadforge.utils.retry import retry_call
from leadforge.utils.snapshots import save_html_snapshot
from leadforge.utils.throttle import DailyRequestCap, DomainThrottle

log = structlog.get_logger("leadforge.scrapers")


class BaseScraper(ABC):
    """One data source, behind one interface (README §12).

    Implementations stay source-specific and side-effect-light: no throttling,
    no DB, no retries — the :class:`ScrapeRunner` supplies all of that.
    """

    source_name: str

    @abstractmethod
    def discover(self, query: SearchQuery) -> Iterator[str]:
        """Yield candidate profile/listing/post URLs for a search."""

    @abstractmethod
    def extract(self, url: str) -> RawLead:
        """Extract raw fields from one page. Raise a typed scraper error on failure."""


class CheckpointStore(Protocol):
    """Persistence for resume state, injected so the runner stays DB-agnostic."""

    def load(self, source: str, query: str) -> dict[str, object] | None:
        """Return saved state for a (source, query), or ``None`` if none exists."""

    def save(self, source: str, query: str, state: dict[str, object]) -> None:
        """Persist resume state for a (source, query)."""


class RunRecorder(Protocol):
    """Persistence for run audit rows + daily-usage accounting (README §12)."""

    def start(self, run_id: str, source: str, query: str) -> None:
        """Record the start of a run."""

    def finish(self, summary: RunSummary) -> None:
        """Record final counts, status, and duration for a run."""

    def requests_used_today(self, source: str) -> int:
        """How many requests this source has already spent today (for the daily cap)."""


@dataclass
class RunSummary:
    """Outcome of one scrape run — mirrors the ``scrape_runs`` row (README §12)."""

    run_id: str
    source: str
    query: str
    status: str = "running"  # running | completed | aborted
    pages_visited: int = 0
    leads_found: int = 0
    rejects: int = 0
    errors: int = 0
    stored_new: int = 0
    stored_updated: int = 0
    duration_seconds: float | None = None
    message: str | None = None
    snapshots: list[str] = field(default_factory=list)


def _domain_of(url: str) -> str:
    """Registrable host of a URL, used as the throttle key."""
    return urlsplit(url).netloc.lower()


# A handler consumes each successfully extracted RawLead (e.g. map + persist).
RawLeadHandler = Callable[[RawLead], None]


class ScrapeRunner:
    """Wraps a :class:`BaseScraper` with throttle, retry, checkpoint, and kill switch."""

    def __init__(
        self,
        scraper: BaseScraper,
        settings: Settings,
        *,
        checkpoint_store: CheckpointStore,
        run_recorder: RunRecorder,
        throttle: DomainThrottle | None = None,
        now: Callable[[], float] = time.monotonic,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.scraper = scraper
        self.settings = settings
        self.checkpoints = checkpoint_store
        self.recorder = run_recorder
        self.throttle = throttle or DomainThrottle(
            settings.scrape_delay_min, settings.scrape_delay_max
        )
        self._now = now
        self._retry_sleep = retry_sleep

    def run(
        self,
        query: SearchQuery,
        *,
        run_id: str,
        handler: RawLeadHandler,
        resume: bool = False,
    ) -> RunSummary:
        """Execute the full run, invoking ``handler`` for each extracted RawLead.

        Returns a :class:`RunSummary`; ``handler`` failures never abort the run —
        one bad page is skipped, not fatal (README §22).
        """
        source = self.scraper.source_name
        query_key = query.need
        summary = RunSummary(run_id=run_id, source=source, query=query_key)
        started = self._now()

        structlog.contextvars.bind_contextvars(run_id=run_id, source=source)
        self.recorder.start(run_id, source, query_key)
        try:
            self._run_loop(query, resume=resume, handler=handler, summary=summary)
            if summary.status == "running":
                summary.status = "completed"
        finally:
            summary.duration_seconds = self._now() - started
            self.recorder.finish(summary)
            structlog.contextvars.unbind_contextvars("run_id", "source")
        return summary

    def _run_loop(
        self,
        query: SearchQuery,
        *,
        resume: bool,
        handler: RawLeadHandler,
        summary: RunSummary,
    ) -> None:
        source = self.scraper.source_name
        query_key = query.need

        state = self.checkpoints.load(source, query_key) if resume else None
        seen: set[str] = set()
        if state:
            saved_urls = state.get("seen_urls", [])
            if isinstance(saved_urls, list):
                seen = {str(u) for u in saved_urls}
        if resume and seen:
            log.info("scrape.resume", seen=len(seen))

        cap = DailyRequestCap(
            self.settings.scrape_daily_cap,
            already_used=self.recorder.requests_used_today(source),
        )
        consecutive_blocks = 0
        limit = query.limit

        for url in self.scraper.discover(query):
            if url in seen:
                continue
            if limit is not None and summary.leads_found >= limit:
                log.info("scrape.limit_reached", limit=limit)
                break
            if not cap.allow():
                summary.message = f"daily request cap reached ({cap.limit})"
                log.warning("scrape.daily_cap_reached", cap=cap.limit)
                break

            self.throttle.wait(_domain_of(url))
            summary.pages_visited += 1

            try:
                raw = self._extract_with_retry(url)
            except BlockedError as exc:
                consecutive_blocks += 1
                log.warning(
                    "scrape.blocked", url=url, consecutive=consecutive_blocks, error=str(exc)
                )
                if consecutive_blocks >= self.settings.scrape_authwall_limit:
                    summary.status = "aborted"
                    summary.message = (
                        f"aborted after {consecutive_blocks} consecutive blocks "
                        f"(authwall/CAPTCHA). Stop and try later or reduce volume — "
                        f"this is a compliance stop, not an error to bypass."
                    )
                    log.error("scrape.killswitch", consecutive=consecutive_blocks)
                    break
                continue
            except ParseError as exc:
                summary.rejects += 1
                self._snapshot(exc, summary)
                continue
            except TransientError as exc:
                summary.errors += 1
                log.warning("scrape.transient_failed", url=url, error=str(exc))
                continue

            consecutive_blocks = 0
            seen.add(url)
            summary.leads_found += 1
            self._handle(raw, handler, summary)
            self._maybe_checkpoint(source, query_key, seen, summary)

        # Final checkpoint so a completed or capped run records everything seen.
        self.checkpoints.save(source, query_key, {"seen_urls": sorted(seen)})

    def _extract_with_retry(self, url: str) -> RawLead:
        """Extract one page, retrying only transient failures (README §12)."""
        return retry_call(
            lambda: self.scraper.extract(url),
            retries=self.settings.scrape_max_retries,
            exceptions=(TransientError,),
            sleep=self._retry_sleep,
        )

    def _handle(self, raw: RawLead, handler: RawLeadHandler, summary: RunSummary) -> None:
        try:
            handler(raw)
        except Exception as exc:  # noqa: BLE001 — a bad record must never kill the run
            summary.rejects += 1
            log.warning("scrape.handler_failed", url=raw.source_url, error=str(exc))

    def _maybe_checkpoint(
        self, source: str, query_key: str, seen: set[str], summary: RunSummary
    ) -> None:
        if summary.leads_found % self.settings.scrape_checkpoint_every == 0:
            self.checkpoints.save(source, query_key, {"seen_urls": sorted(seen)})
            log.debug("scrape.checkpoint", seen=len(seen))

    def _snapshot(self, exc: ParseError, summary: RunSummary) -> None:
        if exc.html is None:
            log.warning("scrape.parse_failed", url=exc.url, error=str(exc))
            return
        path = save_html_snapshot(exc.html, exc.url)
        summary.snapshots.append(str(path))
        log.warning("scrape.parse_failed", url=exc.url, snapshot=str(path), error=str(exc))
