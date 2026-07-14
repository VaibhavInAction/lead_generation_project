"""Repository behavior against a temp SQLite DB (README §7, §23).

These exercise the data layer's contract: dedup lookups, upsert-preserving
provenance, checkpoint save/update, and SQLite FK enforcement — all through
repositories, never raw SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import (
    CheckpointRepository,
    IntentLeadRepository,
    LeadRepository,
    RejectRepository,
    ScrapeRunRepository,
)
from leadforge.models.base import Base
from leadforge.models.enums import IntentStatus, LeadStatus
from leadforge.models.orm import IntentLead, Lead, Reject, ScrapeRun


@pytest.fixture
def session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    """A sessionmaker bound to a throwaway file-backed SQLite DB with schema created."""
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session for a single test; repos flush, so no commit is needed to query.

    Rolled back on teardown — this also cleanly recovers from tests that
    intentionally trigger an ``IntegrityError``.
    """
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _make_lead(**overrides: object) -> Lead:
    data: dict[str, object] = {
        "business_name": "Acme Media",
        "lead_source": "linkedin",
        "source_url": "https://example.com/acme",
    }
    data.update(overrides)
    return Lead(**data)


def _make_intent(**overrides: object) -> IntentLead:
    data: dict[str, object] = {
        "author_name": "Jane Doe",
        "need_text": "looking for a video editor",
        "need_category": "video_editing",
        "post_url": "https://linkedin.com/posts/jane_123",
        "post_text": "Hey, anyone know a good video editor?",
        "platform": "linkedin_public",
    }
    data.update(overrides)
    return IntentLead(**data)


class TestSessionScope:
    def test_commits_on_success(self, session_factory: sessionmaker[Session]) -> None:
        with session_scope(session_factory) as s:
            LeadRepository(s).add(_make_lead(domain="acme.com"))
        # A fresh session sees the committed row.
        with session_scope(session_factory) as s:
            assert LeadRepository(s).get_by_domain("acme.com") is not None

    def test_rolls_back_on_error(self, session_factory: sessionmaker[Session]) -> None:
        with pytest.raises(RuntimeError), session_scope(session_factory) as s:
            LeadRepository(s).add(_make_lead(domain="acme.com"))
            raise RuntimeError("boom")
        with session_scope(session_factory) as s:
            assert LeadRepository(s).count() == 0


class TestLeadRepository:
    def test_add_sets_defaults_and_roundtrips(self, session: Session) -> None:
        repo = LeadRepository(session)
        lead = repo.add(_make_lead(domain="acme.com"))

        fetched = repo.get(lead.id)
        assert fetched is not None
        assert fetched.business_name == "Acme Media"
        # Server-side defaults populated on flush.
        assert fetched.status is LeadStatus.NEW
        assert fetched.data_quality_score == 0
        assert fetched.keywords == []
        assert fetched.first_seen is not None

    def test_get_by_domain(self, session: Session) -> None:
        repo = LeadRepository(session)
        repo.add(_make_lead(domain="acme.com"))
        assert repo.get_by_domain("acme.com") is not None
        assert repo.get_by_domain("missing.com") is None

    def test_get_by_source_url(self, session: Session) -> None:
        repo = LeadRepository(session)
        repo.add(_make_lead(source_url="https://example.com/x"))
        assert repo.get_by_source_url("https://example.com/x") is not None
        assert repo.get_by_source_url("https://example.com/nope") is None

    def test_count_and_list(self, session: Session) -> None:
        repo = LeadRepository(session)
        for i in range(3):
            repo.add(_make_lead(source_url=f"https://example.com/{i}"))
        assert repo.count() == 3
        assert len(repo.list(limit=2)) == 2


class TestIntentLeadRepository:
    def test_get_by_post_url(self, session: Session) -> None:
        repo = IntentLeadRepository(session)
        repo.add(_make_intent())
        assert repo.get_by_post_url("https://linkedin.com/posts/jane_123") is not None
        assert repo.get_by_post_url("https://linkedin.com/posts/other") is None

    def test_duplicate_post_url_rejected(self, session: Session) -> None:
        repo = IntentLeadRepository(session)
        repo.add(_make_intent())
        with pytest.raises(IntegrityError):
            repo.add(_make_intent())  # same post_url — unique constraint

    def test_upsert_creates_then_updates_preserving_first_seen(self, session: Session) -> None:
        repo = IntentLeadRepository(session)
        old = datetime(2020, 1, 1, tzinfo=UTC)
        created = repo.upsert_by_post_url(_make_intent(first_seen=old, freshness_score=10))
        assert created.freshness_score == 10

        updated = repo.upsert_by_post_url(
            _make_intent(freshness_score=99, status=IntentStatus.SCORED)
        )
        assert updated.id == created.id  # same row, not a duplicate
        assert repo.count() == 1
        assert updated.freshness_score == 99
        assert updated.status is IntentStatus.SCORED
        # Provenance is preserved across the upsert.
        assert updated.first_seen == old

    def test_fk_set_null_on_lead_delete(self, session: Session) -> None:
        """SQLite FK enforcement is on: deleting a linked Lead nulls the link (README §14)."""
        lead = LeadRepository(session).add(_make_lead(domain="acme.com"))
        intent = IntentLeadRepository(session).add(_make_intent(lead_id=lead.id))
        session.flush()
        assert intent.lead_id == lead.id

        session.delete(lead)
        session.flush()
        session.refresh(intent)
        assert intent.lead_id is None


class TestRejectRepository:
    def test_add_and_count(self, session: Session) -> None:
        repo = RejectRepository(session)
        repo.add(
            Reject(
                source="linkedin",
                stage="validation",
                reason="missing author_name",
                raw_data={"post_url": "x"},
            )
        )
        assert repo.count() == 1


class TestScrapeRunRepository:
    def test_get_by_run_id(self, session: Session) -> None:
        repo = ScrapeRunRepository(session)
        repo.add(ScrapeRun(run_id="run-abc", source="linkedin"))
        found = repo.get_by_run_id("run-abc")
        assert found is not None
        assert found.status == "running"  # default
        assert repo.get_by_run_id("nope") is None


class TestCheckpointRepository:
    def test_save_creates_then_updates(self, session: Session) -> None:
        repo = CheckpointRepository(session)
        cp = repo.save("linkedin", {"page": 1}, query="marketing")
        assert cp.state == {"page": 1}

        again = repo.save("linkedin", {"page": 5}, query="marketing")
        assert again.id == cp.id  # same (source, query) → updated in place
        assert repo.count() == 1
        assert again.state == {"page": 5}

    def test_get_for_scopes_by_source_and_query(self, session: Session) -> None:
        repo = CheckpointRepository(session)
        repo.save("linkedin", {"page": 1}, query="marketing")
        assert repo.get_for("linkedin", "marketing") is not None
        assert repo.get_for("linkedin", "other") is None
        assert repo.get_for("reddit", "marketing") is None
