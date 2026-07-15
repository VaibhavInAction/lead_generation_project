"""Scoring service + `intent score` / filtered list CLI (README §16, §21, §23).

End-to-end over a tiny SQLite DB seeded with the real client vs. hiring posts:
scoring must classify, rank client leads above job postings, and the CLI must
default to client-only, honor --category, and honor --max-age.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from leadforge.cli.app import app
from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import IntentLeadRepository
from leadforge.models.base import Base
from leadforge.models.enums import IntentStatus, PostCategory
from leadforge.models.orm import IntentLead
from leadforge.services.intent_score import build_intent_score_service

runner = CliRunner()

CLIENT_POST = (
    "Looking for a marketing agency to help our D2C brand grow. "
    "Anyone recommend a good one in Mumbai?"
)
HIRING_POST = (
    "URGENT HIRING | Google Ads Expert needed to join our team. "
    "Full-time position, apply now! Send your CV."
)


def _lead(
    author: str,
    slug: str,
    post_text: str,
    *,
    need: str = "marketing agency",
    posted_at: datetime | None = None,
    first_seen: datetime | None = None,
    data_quality: int = 80,
) -> IntentLead:
    return IntentLead(
        author_name=author,
        need_text=post_text[:120],
        need_category=need,
        post_url=f"https://www.linkedin.com/posts/{slug}",
        post_text=post_text,
        posted_at=posted_at,
        first_seen=first_seen or datetime(2026, 7, 15, tzinfo=UTC),
        platform="linkedin_public",
        data_quality_score=data_quality,
    )


def _make_db(path, leads: list[IntentLead]) -> Settings:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{path}", scoring_path="nope.yaml")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        repo = IntentLeadRepository(session)
        for lead in leads:
            repo.add(lead)
    engine.dispose()
    return settings


def test_service_scores_and_classifies(tmp_path) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    settings = _make_db(
        tmp_path / "s.db",
        [
            _lead("Client Co", "client_1", CLIENT_POST, posted_at=now),
            _lead("Recruiter Inc", "job_1", HIRING_POST, need="Google Ads expert", posted_at=now),
        ],
    )

    service = build_intent_score_service(settings)
    summary = service.run(now=now)

    assert summary.total == 2
    assert summary.client_leads == 1
    assert summary.by_category == {"client_lead": 1, "job_posting": 1}

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        repo = IntentLeadRepository(session)
        by_author = {lead.author_name: lead for lead in repo.list_recent()}
    engine.dispose()

    client = by_author["Client Co"]
    job = by_author["Recruiter Inc"]
    assert client.category == PostCategory.CLIENT_LEAD
    assert client.status == IntentStatus.SCORED
    assert client.lead_score is not None and client.lead_score >= 70
    assert job.category == PostCategory.JOB_POSTING
    assert job.lead_score == 0  # forced to the bottom
    # The client lead outranks the (equally fresh) job posting.
    assert client.lead_score > job.lead_score


def test_intent_score_cli_reports_counts(tmp_path, monkeypatch) -> None:
    settings = _make_db(
        tmp_path / "s.db",
        [
            _lead("Client Co", "client_1", CLIENT_POST),
            _lead("Recruiter Inc", "job_1", HIRING_POST, need="Google Ads expert"),
        ],
    )
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SCORING_PATH", "nope.yaml")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "score"])
    assert result.exit_code == 0, result.output
    assert "Scored 2 of 2" in result.output
    # One line per category; the two present here show a count of 1.
    assert "client_lead" in result.output
    assert "job_posting" in result.output
    assert "your outreach list" in result.output


def test_intent_list_defaults_to_client_leads_only(tmp_path, monkeypatch) -> None:
    settings = _make_db(
        tmp_path / "s.db",
        [
            _lead("Client Co", "client_1", CLIENT_POST),
            _lead("Recruiter Inc", "job_1", HIRING_POST, need="Google Ads expert"),
        ],
    )
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SCORING_PATH", "nope.yaml")
    get_settings.cache_clear()

    assert runner.invoke(app, ["intent", "score"]).exit_code == 0

    # Default: only client leads are shown; the recruiter is hidden.
    default = runner.invoke(app, ["intent", "list"])
    assert default.exit_code == 0, default.output
    assert "Client Co" in default.output
    assert "Recruiter Inc" not in default.output
    assert "client_lead" in default.output

    # --category job_posting reveals the excluded recruiter.
    jobs = runner.invoke(app, ["intent", "list", "--category", "job_posting"])
    assert jobs.exit_code == 0, jobs.output
    assert "Recruiter Inc" in jobs.output
    assert "Client Co" not in jobs.output

    # --category all shows both.
    everything = runner.invoke(app, ["intent", "list", "--category", "all"])
    assert "Client Co" in everything.output
    assert "Recruiter Inc" in everything.output


def test_intent_list_rejects_bad_category(tmp_path, monkeypatch) -> None:
    settings = _make_db(tmp_path / "s.db", [_lead("Client Co", "c1", CLIENT_POST)])
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "list", "--category", "bogus"])
    assert result.exit_code == 1
    assert "invalid" in result.output


def test_intent_list_max_age_filters_old_posts(tmp_path, monkeypatch) -> None:
    now = datetime.now(UTC)
    settings = _make_db(
        tmp_path / "s.db",
        [
            _lead("Fresh Co", "fresh", CLIENT_POST, posted_at=now - timedelta(days=1)),
            _lead("Stale Co", "stale", CLIENT_POST, posted_at=now - timedelta(days=40)),
        ],
    )
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SCORING_PATH", "nope.yaml")
    get_settings.cache_clear()

    assert runner.invoke(app, ["intent", "score"]).exit_code == 0

    result = runner.invoke(app, ["intent", "list", "--max-age", "7"])
    assert result.exit_code == 0, result.output
    assert "Fresh Co" in result.output
    assert "Stale Co" not in result.output


def test_intent_export_defaults_to_client_leads(tmp_path, monkeypatch) -> None:
    import csv

    settings = _make_db(
        tmp_path / "s.db",
        [
            _lead("Client Co", "client_1", CLIENT_POST),
            _lead("Recruiter Inc", "job_1", HIRING_POST, need="Google Ads expert"),
        ],
    )
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SCORING_PATH", "nope.yaml")
    get_settings.cache_clear()
    assert runner.invoke(app, ["intent", "score"]).exit_code == 0

    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["intent", "export", "--format", "csv", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "Exported 1 intent lead" in result.output  # only the client lead

    with out.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.reader(handle))
    authors = [r[0] for r in records[1:]]
    assert authors == ["Client Co"]
