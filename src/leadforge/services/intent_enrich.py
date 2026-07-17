"""Intent-lead enrichment orchestration (README §14, Phase 8).

Reads every stored :class:`IntentLead`, re-runs the heuristic enricher over its
post text + headline, and writes back ``company`` / ``contact_email`` /
``website``. Pure extraction lives in :mod:`leadforge.enrichment.intent_enrich`;
this layer just wires it to persistence. Idempotent: post text doesn't change, so
re-running yields the same values. ``company`` is only *filled* (never clobbered),
preserving a value the scraper already resolved from the headline.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import IntentLeadRepository
from leadforge.enrichment.intent_enrich import enrich_intent_lead

log = structlog.get_logger("leadforge.services.intent_enrich")


@dataclass
class EnrichSummary:
    """Counts from an enrichment pass — leads seen and how many carry each fact."""

    total: int = 0
    with_company: int = 0
    with_email: int = 0
    with_website: int = 0


class IntentEnrichService:
    """(Re)enriches stored intent leads in place (README §14)."""

    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self._sessions = session_factory

    def run(self) -> EnrichSummary:
        """Enrich every stored intent lead and return the tally."""
        summary = EnrichSummary()
        with session_scope(self._sessions) as session:
            for lead in IntentLeadRepository(session).list_recent():
                summary.total += 1
                result = enrich_intent_lead(
                    post_text=lead.post_text, author_headline=lead.author_headline
                )
                lead.company = lead.company or result.company
                lead.contact_email = result.contact_email or lead.contact_email
                lead.website = result.website or lead.website
                summary.with_company += bool(lead.company)
                summary.with_email += bool(lead.contact_email)
                summary.with_website += bool(lead.website)
        log.info(
            "intent.enriched",
            total=summary.total,
            with_company=summary.with_company,
            with_email=summary.with_email,
            with_website=summary.with_website,
        )
        return summary


def build_intent_enrich_service(
    settings: Settings, *, engine: Engine | None = None
) -> IntentEnrichService:
    """Assemble the enrichment service with a DB session factory (README §24)."""
    engine = engine or create_db_engine(settings)
    session_factory = create_session_factory(engine)
    return IntentEnrichService(settings, session_factory)
