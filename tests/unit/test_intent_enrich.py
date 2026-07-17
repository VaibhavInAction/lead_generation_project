"""Heuristic enrichment for intent leads (Phase 8, README §17, §23).

Offline fixtures built from the real post examples: a company stated in the post
or headline, a public email, and a website — with the hard rule that anything not
clearly present stays ``None`` (a blank beats a guess).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from leadforge.cli.app import app
from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import IntentLeadRepository
from leadforge.enrichment.intent_enrich import (
    enrich_intent_lead,
    extract_company,
    extract_email,
    extract_website,
)
from leadforge.models.base import Base
from leadforge.models.orm import IntentLead
from leadforge.services.intent_enrich import build_intent_enrich_service

runner = CliRunner()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Reach us at contact@nhabit.com for details.", "contact@nhabit.com"),
        ("Please email Shauna@bairdtalent.com to apply.", "shauna@bairdtalent.com"),
        ("Looking for a marketing agency in Mumbai.", None),
    ],
)
def test_extract_email(text: str, expected: str | None) -> None:
    assert extract_email(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("See https://nhabit.com/careers for more.", "https://nhabit.com/careers"),
        ("Visit www.instazorb.com to learn more.", "https://www.instazorb.com"),
        ("No links here, just a plain need for help.", None),
    ],
)
def test_extract_website(text: str, expected: str | None) -> None:
    assert extract_website(text) == expected


@pytest.mark.parametrize(
    ("post_text", "headline", "expected"),
    [
        ("Unify Search Solutions Pvt. Ltd. is looking for a video editor.", None,
         "Unify Search Solutions Pvt. Ltd."),
        ("Hey folks, we're InstaZorb and we need a brand refresh.", None, "InstaZorb"),
        ("We are hiring across the board.", "Founder at nHabit", "nHabit"),
        ("Looking for a marketing agency to grow our D2C brand.", None, None),
        # "We're Hiring" names no company — "Hiring" is a stopword, not a name.
        ("We're Hiring: #PPCSpecialist for our team.", None, None),
    ],
)
def test_extract_company(post_text: str, headline: str | None, expected: str | None) -> None:
    assert extract_company(post_text, headline) == expected


def test_enrich_intent_lead_pulls_all_three() -> None:
    result = enrich_intent_lead(
        post_text="InstaZorb is hiring. Reach us at contact@nhabit.com or www.nhabit.com.",
        author_headline=None,
    )
    assert result.company == "InstaZorb"
    assert result.contact_email == "contact@nhabit.com"
    assert result.website == "https://www.nhabit.com"


def test_enrich_intent_lead_blank_when_nothing_present() -> None:
    result = enrich_intent_lead(
        post_text="Looking for a marketing agency to help our brand grow.",
        author_headline=None,
    )
    assert result.company is None
    assert result.contact_email is None
    assert result.website is None


def _make_db(path, leads: list[IntentLead]) -> Settings:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{path}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        repo = IntentLeadRepository(session)
        for lead in leads:
            repo.add(lead)
    engine.dispose()
    return settings


def _lead(slug: str, post_text: str, *, headline: str | None = None) -> IntentLead:
    return IntentLead(
        author_name="Someone",
        author_headline=headline,
        need_text=post_text[:120],
        need_category="marketing",
        post_url=f"https://www.linkedin.com/posts/{slug}",
        post_text=post_text,
        platform="linkedin_public",
    )


def test_service_enriches_stored_leads(tmp_path) -> None:
    settings = _make_db(
        tmp_path / "e.db",
        [
            _lead("l1", "InstaZorb is hiring. Reach contact@nhabit.com — see www.nhabit.com."),
            _lead("l2", "We are hiring a video editor.", headline="Founder at nHabit"),
            _lead("l3", "Just looking for an agency, no details."),
        ],
    )

    summary = build_intent_enrich_service(settings).run()

    assert summary.total == 3
    assert summary.with_company == 2  # InstaZorb + nHabit (headline)
    assert summary.with_email == 1
    assert summary.with_website == 1

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        by_slug = {
            lead.post_url.rsplit("/", 1)[-1]: lead
            for lead in IntentLeadRepository(session).list_recent()
        }
    engine.dispose()

    assert by_slug["l1"].company == "InstaZorb"
    assert by_slug["l1"].contact_email == "contact@nhabit.com"
    assert by_slug["l1"].website == "https://www.nhabit.com"
    assert by_slug["l2"].company == "nHabit"
    assert by_slug["l3"].company is None
    assert by_slug["l3"].contact_email is None


def test_intent_enrich_cli_reports_counts(tmp_path, monkeypatch) -> None:
    settings = _make_db(
        tmp_path / "e.db",
        [_lead("l1", "Reach us at contact@nhabit.com — InstaZorb is hiring.")],
    )
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "enrich"])
    assert result.exit_code == 0, result.output
    assert "Enriched 1 intent lead" in result.output
    assert "with company" in result.output
    assert "with email" in result.output
