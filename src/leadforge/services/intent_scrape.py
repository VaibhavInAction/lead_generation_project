"""Intent scraping orchestration (README §7, §8, §14).

The service layer wires a (DB-ignorant) scraper to persistence: it drives the
:class:`ScrapeRunner`, maps each :class:`RawLead` to an :class:`IntentLead`,
cleans + quality-scores it (Phase 6), and upserts it deduped by ``post_url`` — so
stored leads are already clean and carry a ``data_quality_score``. Freshness/ICP
scoring (Phase 9) still runs later over the persisted rows.

The SQL-backed :class:`SqlCheckpointStore` / :class:`SqlRunRecorder` implement the
runner's injected protocols; each uses its own short transaction so checkpoints
and the run row are durable even if the process dies mid-run (README §8).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import (
    CheckpointRepository,
    IntentLeadRepository,
    RejectRepository,
    ScrapeRunRepository,
)
from leadforge.models.base import utcnow
from leadforge.models.orm import Reject, ScrapeRun
from leadforge.models.schemas import RawLead, SearchQuery
from leadforge.scrapers.base import BaseScraper, RunSummary, ScrapeRunner
from leadforge.scrapers.intent.mapping import MappingError, raw_to_intent_lead
from leadforge.scrapers.registry import get_scraper
from leadforge.validation.intent import ValidationError, assess_intent_lead

log = structlog.get_logger("leadforge.services.intent_scrape")


def _day_start(now: datetime) -> datetime:
    """UTC midnight for ``now`` — the boundary of the daily request cap."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class SqlCheckpointStore:
    """Checkpoint persistence backed by :class:`CheckpointRepository`."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def load(self, source: str, query: str) -> dict[str, object] | None:
        with session_scope(self._sessions) as session:
            checkpoint = CheckpointRepository(session).get_for(source, query)
            return dict(checkpoint.state) if checkpoint else None

    def save(self, source: str, query: str, state: dict[str, object]) -> None:
        with session_scope(self._sessions) as session:
            CheckpointRepository(session).save(source, state, query=query)


class SqlRunRecorder:
    """``scrape_runs`` persistence + daily-usage accounting (README §12)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def start(self, run_id: str, source: str, query: str) -> None:
        with session_scope(self._sessions) as session:
            ScrapeRunRepository(session).add(
                ScrapeRun(run_id=run_id, source=source, query=query, status="running")
            )

    def finish(self, summary: RunSummary) -> None:
        with session_scope(self._sessions) as session:
            run = ScrapeRunRepository(session).get_by_run_id(summary.run_id)
            if run is None:  # pragma: no cover — start() always precedes finish()
                return
            run.status = summary.status
            run.pages_visited = summary.pages_visited
            run.leads_found = summary.leads_found
            run.rejects = summary.rejects
            run.errors = summary.errors
            run.duration_seconds = summary.duration_seconds
            run.error_message = summary.message
            run.finished_at = utcnow()

    def requests_used_today(self, source: str) -> int:
        with session_scope(self._sessions) as session:
            return ScrapeRunRepository(session).requests_since(source, _day_start(utcnow()))


class IntentScrapeService:
    """Discovers, extracts, and stores intent leads for one need (README §14)."""

    def __init__(
        self,
        scraper: BaseScraper,
        settings: Settings,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.scraper = scraper
        self.settings = settings
        self._sessions = session_factory

    def run(
        self,
        *,
        need: str,
        since: str = "7d",
        limit: int | None = None,
        resume: bool = False,
    ) -> RunSummary:
        """Run discovery→extraction→store for ``need`` and return the run summary."""
        query = SearchQuery(need=need, since=since, limit=limit)
        runner = ScrapeRunner(
            self.scraper,
            self.settings,
            checkpoint_store=SqlCheckpointStore(self._sessions),
            run_recorder=SqlRunRecorder(self._sessions),
        )
        # The handler runs *during* runner.run(), before the summary is returned,
        # so store counts accumulate here and are folded into the summary after.
        counts = {"new": 0, "updated": 0}
        summary = runner.run(
            query,
            run_id=uuid4().hex[:12],
            handler=lambda raw: self._store(raw, need, counts),
            resume=resume,
        )
        summary.stored_new = counts["new"]
        summary.stored_updated = counts["updated"]
        return summary

    def _store(self, raw: RawLead, need: str, counts: dict[str, int]) -> None:
        """Map, clean, quality-score, and upsert one lead, deduped by post_url.

        Hard failures (mapping or validation) go to ``rejects`` with a reason and
        the error is re-raised so the run counts it (never silently dropped, §8).
        Soft issues are kept and recorded in ``quality_flags`` (README §17).
        """
        try:
            lead = raw_to_intent_lead(raw, need_category=need)
        except MappingError as exc:
            self._reject(raw, str(exc), stage="mapping")
            raise

        # Phase 6: clean the fields and compute a data-quality score before storing.
        assessment = assess_intent_lead(
            author_name=lead.author_name,
            author_headline=lead.author_headline,
            company=lead.company,
            need_text=lead.need_text,
            post_text=lead.post_text,
            posted_at=lead.posted_at,
            author_profile_url=lead.author_profile_url,
        )
        if assessment.rejected:
            reason = assessment.reason or "validation failed"
            self._reject(raw, reason, stage="validation")
            raise ValidationError(reason)

        lead.author_name = assessment.author_name
        lead.author_headline = assessment.author_headline
        lead.company = assessment.company
        lead.need_text = assessment.need_text
        lead.post_text = assessment.post_text
        lead.data_quality_score = assessment.data_quality_score
        lead.quality_flags = assessment.quality_flags

        with session_scope(self._sessions) as session:
            repo = IntentLeadRepository(session)
            existed = repo.get_by_post_url(lead.post_url) is not None
            repo.upsert_by_post_url(lead)
        counts["updated" if existed else "new"] += 1

    def _reject(self, raw: RawLead, reason: str, *, stage: str) -> None:
        with session_scope(self._sessions) as session:
            RejectRepository(session).add(
                Reject(
                    source=raw.source,
                    stage=stage,
                    reason=reason,
                    raw_data=dict(raw.data),
                    source_url=raw.source_url,
                )
            )


def build_intent_scrape_service(
    source: str, settings: Settings, *, engine: Engine | None = None
) -> IntentScrapeService:
    """Assemble the service with a live scraper + DB session factory (README §24)."""
    engine = engine or create_db_engine(settings)
    session_factory = create_session_factory(engine)
    scraper = get_scraper(source, settings)
    return IntentScrapeService(scraper, settings, session_factory)
