"""End-to-end intent scraping against a temp DB, driven by a fake scraper (README §14, §23)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import (
    CheckpointRepository,
    IntentLeadRepository,
    RejectRepository,
    ScrapeRunRepository,
)
from leadforge.models.base import Base
from leadforge.models.schemas import RawLead
from leadforge.services.intent_scrape import IntentScrapeService

from .conftest import FakeScraper

URLS = ["https://www.linkedin.com/posts/jane_1", "https://www.linkedin.com/posts/ravi_2"]


def _good_extract(url: str) -> RawLead:
    return RawLead(
        source="linkedin_posts",
        source_url=url,
        data={
            "author_name": "Jane Doe",
            "author_headline": "Founder at Acme Studios",
            "author_profile_url": "https://www.linkedin.com/in/jane-doe",
            "post_text": "We are looking for a marketing agency.",
            "posted_at": datetime(2026, 7, 10, tzinfo=UTC),
        },
    )


@pytest.fixture
def session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'svc.db'}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    try:
        yield create_session_factory(engine)
    finally:
        engine.dispose()


def _settings(tmp_path) -> Settings:
    # Zero delays keep the real throttle instant; DB is the temp file.
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'svc.db'}",
        scrape_delay_min=0.0,
        scrape_delay_max=0.0,
    )


def _service(scraper: FakeScraper, tmp_path, sf: sessionmaker[Session]) -> IntentScrapeService:
    return IntentScrapeService(scraper, _settings(tmp_path), sf)


def test_stores_extracted_intent_leads(tmp_path, session_factory) -> None:
    scraper = FakeScraper(URLS, _good_extract, source_name="linkedin_posts")
    service = _service(scraper, tmp_path, session_factory)

    summary = service.run(need="marketing", since="30d")

    assert summary.status == "completed"
    assert summary.leads_found == 2
    assert summary.stored_new == 2
    assert summary.stored_updated == 0

    with session_scope(session_factory) as s:
        leads = IntentLeadRepository(s)
        assert leads.count() == 2
        jane = leads.get_by_post_url(URLS[0])
        assert jane is not None
        assert jane.need_category == "marketing"
        assert jane.company == "Acme Studios"
        assert jane.platform == "linkedin_public"

        runs = ScrapeRunRepository(s)
        assert runs.count() == 1
        stored_run = runs.list()[0]
        assert stored_run.status == "completed"
        assert stored_run.leads_found == 2
        assert stored_run.finished_at is not None

        assert CheckpointRepository(s).get_for("linkedin_posts", "marketing") is not None


def test_rerun_deduplicates_by_post_url(tmp_path, session_factory) -> None:
    scraper = FakeScraper(URLS, _good_extract, source_name="linkedin_posts")
    service = _service(scraper, tmp_path, session_factory)

    service.run(need="marketing", since="30d")
    summary2 = service.run(need="marketing", since="30d")

    assert summary2.stored_new == 0
    assert summary2.stored_updated == 2
    with session_scope(session_factory) as s:
        assert IntentLeadRepository(s).count() == 2  # still two, not four


def test_unmappable_record_goes_to_rejects(tmp_path, session_factory) -> None:
    def extractor(url: str) -> RawLead:
        if url == URLS[0]:
            # Missing author_name → cannot form an IntentLead.
            return RawLead(source="linkedin_posts", source_url=url, data={"post_text": "hi"})
        return _good_extract(url)

    scraper = FakeScraper(URLS, extractor, source_name="linkedin_posts")
    service = _service(scraper, tmp_path, session_factory)

    summary = service.run(need="marketing", since="30d")

    assert summary.stored_new == 1
    assert summary.rejects == 1
    with session_scope(session_factory) as s:
        assert IntentLeadRepository(s).count() == 1
        rejects = RejectRepository(s)
        assert rejects.count() == 1
        assert rejects.list()[0].stage == "mapping"
