"""Intent-lead scoring orchestration (README §14, §16, Phase 9).

Reads every stored :class:`IntentLead`, classifies it (client lead vs. job
posting), scores freshness + need-match, and writes back ``category``,
``freshness_score``, and the blended ``lead_score`` — flipping the lead's status
to ``scored``. Freshness decays with wall-clock time, so re-running is the norm:
a lead scored last week is stale today. Pure scoring logic lives in
:mod:`leadforge.scoring`; this layer just wires it to persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import IntentLeadRepository
from leadforge.models.base import utcnow
from leadforge.models.enums import IntentStatus, PostCategory
from leadforge.scoring import ScoringConfig, load_scoring_config, score_intent_lead

log = structlog.get_logger("leadforge.services.intent_score")


@dataclass
class ScoreSummary:
    """Counts from a scoring pass — total seen and a tally per category."""

    total: int = 0
    scored: int = 0
    by_category: dict[str, int] = field(default_factory=dict)

    @property
    def client_leads(self) -> int:
        """Genuine client leads found — the number that matters."""
        return self.by_category.get(PostCategory.CLIENT_LEAD.value, 0)


class IntentScoreService:
    """(Re)scores stored intent leads in place (README §16)."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        config: ScoringConfig,
    ) -> None:
        self.settings = settings
        self._sessions = session_factory
        self.config = config

    def run(self, *, now: datetime | None = None) -> ScoreSummary:
        """Score every intent lead against the clock ``now`` (defaults to utcnow)."""
        now = now or utcnow()
        summary = ScoreSummary()
        with session_scope(self._sessions) as session:
            repo = IntentLeadRepository(session)
            for lead in repo.list_recent():
                summary.total += 1
                result = score_intent_lead(
                    need_category=lead.need_category,
                    post_text=lead.post_text,
                    author_name=lead.author_name,
                    posted_at=lead.posted_at,
                    first_seen=lead.first_seen,
                    data_quality_score=lead.data_quality_score,
                    now=now,
                    config=self.config,
                )
                lead.category = result.category
                lead.freshness_score = result.freshness
                lead.lead_score = result.lead_score
                lead.status = IntentStatus.SCORED
                summary.scored += 1
                key = result.category.value
                summary.by_category[key] = summary.by_category.get(key, 0) + 1
        log.info("intent.scored", total=summary.total, **summary.by_category)
        return summary


def build_intent_score_service(
    settings: Settings, *, engine: Engine | None = None
) -> IntentScoreService:
    """Assemble the scoring service with a DB session factory + loaded config (README §24)."""
    engine = engine or create_db_engine(settings)
    session_factory = create_session_factory(engine)
    config = load_scoring_config(settings.scoring_path)
    return IntentScoreService(settings, session_factory, config)
