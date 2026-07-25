"""CLI wiring for `leadforge intent scrape` / `intent list` / `daily` (README §21)."""

from __future__ import annotations

from datetime import UTC, datetime

from typer.testing import CliRunner

from leadforge.cli.app import app
from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import create_db_engine, create_session_factory, session_scope
from leadforge.database.repositories import IntentLeadRepository
from leadforge.models.base import Base
from leadforge.models.enums import PostCategory
from leadforge.models.orm import IntentLead
from leadforge.scrapers.base import RunSummary

runner = CliRunner()


def _make_db(path, leads: list[IntentLead]) -> None:
    """Create the schema at ``path`` and insert ``leads`` (test helper)."""
    settings = Settings(_env_file=None, database_url=f"sqlite:///{path}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        repo = IntentLeadRepository(session)
        for lead in leads:
            repo.add(lead)
    engine.dispose()


def test_intent_help_lists_scrape() -> None:
    result = runner.invoke(app, ["intent", "--help"])
    assert result.exit_code == 0
    assert "scrape" in result.output


def test_scrape_rejects_disabled_source(monkeypatch) -> None:
    monkeypatch.setenv("SOURCES_ENABLED", "reddit")  # linkedin_posts switched off
    get_settings.cache_clear()
    result = runner.invoke(app, ["intent", "scrape", "--need", "marketing"])
    assert result.exit_code == 1
    assert "not enabled" in result.output


def test_scrape_runs_and_prints_summary(monkeypatch) -> None:
    monkeypatch.delenv("SOURCES_ENABLED", raising=False)  # default enables linkedin_posts
    get_settings.cache_clear()

    class FakeService:
        def run(self, *, need, since, limit, resume) -> RunSummary:
            return RunSummary(
                run_id="abc123",
                source="linkedin_posts",
                query=need,
                status="completed",
                pages_visited=3,
                leads_found=2,
                stored_new=2,
            )

    monkeypatch.setattr(
        "leadforge.services.intent_scrape.build_intent_scrape_service",
        lambda source, settings: FakeService(),
    )

    result = runner.invoke(app, ["intent", "scrape", "--need", "marketing", "--since", "7d"])
    assert result.exit_code == 0, result.output
    assert "run abc123" in result.output
    assert "stored (new)" in result.output


def test_scrape_all_iterates_all_needs_and_aggregates(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SOURCES_ENABLED", raising=False)  # default enables linkedin_posts
    get_settings.cache_clear()

    needs_file = tmp_path / "needs.yaml"
    needs_file.write_text(
        "needs:\n  - marketing agency\n  - SEO agency\n  - PPC expert\n", encoding="utf-8"
    )

    calls: list[str] = []

    class FakeService:
        def run(self, *, need, since, limit, resume) -> RunSummary:
            calls.append(need)
            return RunSummary(
                run_id=f"r-{len(calls)}",
                source="linkedin_posts",
                query=need,
                status="completed",
                pages_visited=4,
                leads_found=3,
                stored_new=2,
                stored_updated=1,
            )

    monkeypatch.setattr(
        "leadforge.services.intent_scrape.build_intent_scrape_service",
        lambda source, settings: FakeService(),
    )

    result = runner.invoke(
        app, ["intent", "scrape-all", "--since", "30d", "--needs-file", str(needs_file)]
    )

    assert result.exit_code == 0, result.output
    # Every need was scraped, in order.
    assert calls == ["marketing agency", "SEO agency", "PPC expert"]
    for need in calls:
        assert need in result.output
    # Grand total aggregates across the 3 needs (extracted=3, new=2, updated=1 each).
    assert "TOTAL  extracted=9  new=6  updated=3" in result.output
    assert "6 distinct new lead(s) stored" in result.output


def test_scrape_all_reports_missing_needs_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SOURCES_ENABLED", raising=False)
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "scrape-all", "--needs-file", str(tmp_path / "no.yaml")])

    assert result.exit_code == 1
    assert "intent scrape-all" in result.output


def _intent(
    author: str,
    post_slug: str,
    first_seen: datetime,
    *,
    category: str = PostCategory.CLIENT_LEAD,
    lead_score: int | None = None,
) -> IntentLead:
    return IntentLead(
        author_name=author,
        need_text=f"{author} needs marketing",
        need_category="marketing",
        post_url=f"https://www.linkedin.com/posts/{post_slug}",
        post_text=f"{author} post body",
        platform="linkedin_public",
        first_seen=first_seen,
        category=category,
        lead_score=lead_score,
    )


def test_intent_list_shows_leads_most_recent_first(tmp_path, monkeypatch) -> None:
    db = tmp_path / "leads.db"
    _make_db(
        db,
        [
            _intent("Old Author", "old_1", datetime(2026, 1, 1, tzinfo=UTC)),
            _intent("New Author", "new_2", datetime(2026, 6, 1, tzinfo=UTC)),
        ],
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "list"])

    assert result.exit_code == 0, result.output
    assert "New Author" in result.output
    assert "Old Author" in result.output
    # Most recent first: the June lead is listed above the January one.
    assert result.output.index("New Author") < result.output.index("Old Author")
    assert "Showing 2 of 2" in result.output
    # Header row is present (readable table).
    assert "author" in result.output
    assert "post_url" in result.output


def test_intent_list_shows_full_post_url(tmp_path, monkeypatch) -> None:
    long_url = (
        "https://www.linkedin.com/posts/some-really-long-author-slug-1234567890"
        "_activity-9998887776665554443-abcd?utm_source=share&utm_medium=member_desktop"
    )
    db = tmp_path / "leads.db"
    _make_db(
        db,
        [
            IntentLead(
                author_name="Longy McLongface",
                need_text="needs marketing",
                need_category="marketing",
                post_url=long_url,
                post_text="body",
                platform="linkedin_public",
                first_seen=datetime(2026, 1, 1, tzinfo=UTC),
                category=PostCategory.CLIENT_LEAD,
            )
        ],
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "list"])

    assert result.exit_code == 0, result.output
    # The complete URL is present (not truncated with "..."), so it stays clickable.
    assert long_url in result.output


def test_intent_list_respects_limit(tmp_path, monkeypatch) -> None:
    db = tmp_path / "leads.db"
    leads = [
        _intent(f"Author {i}", f"slug_{i}", datetime(2026, 1, i + 1, tzinfo=UTC)) for i in range(5)
    ]
    _make_db(db, leads)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "list", "--limit", "2"])

    assert result.exit_code == 0, result.output
    assert "Showing 2 of 5" in result.output


def test_intent_list_empty(tmp_path, monkeypatch) -> None:
    db = tmp_path / "empty.db"
    _make_db(db, [])
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "list"])

    assert result.exit_code == 0, result.output
    assert "No intent leads match" in result.output


def test_intent_export_csv_writes_file(tmp_path, monkeypatch) -> None:
    import csv

    db = tmp_path / "leads.db"
    _make_db(db, [_intent("Casey Lee", "casey_1", datetime(2026, 5, 1, tzinfo=UTC))])
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["intent", "export", "--format", "csv", "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "Exported 1 intent lead" in result.output
    with out.open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.reader(handle))
    from leadforge.exports.intent import INTENT_COLUMNS

    assert records[0] == list(INTENT_COLUMNS)
    assert records[1][INTENT_COLUMNS.index("author_name")] == "Casey Lee"
    assert records[1][INTENT_COLUMNS.index("category")] == "client_lead"
    # full URL, un-truncated
    assert records[1][INTENT_COLUMNS.index("post_url")] == "https://www.linkedin.com/posts/casey_1"


def test_intent_export_rejects_bad_format(tmp_path, monkeypatch) -> None:
    db = tmp_path / "leads.db"
    _make_db(db, [_intent("Casey Lee", "casey_1", datetime(2026, 5, 1, tzinfo=UTC))])
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["intent", "export", "--format", "pdf"])

    assert result.exit_code == 1
    assert "unsupported --format" in result.output


# --- leadforge daily (the one-command routine) --------------------------------


def _stub_daily_services(
    monkeypatch, calls: list[str], *, scrape_status: str = "completed"
) -> None:
    """Replace the three services `daily` orchestrates with fakes that log their call."""
    from leadforge.services.intent_enrich import EnrichSummary
    from leadforge.services.intent_score import ScoreSummary

    class FakeScrape:
        def run(self, *, need, since, limit, resume) -> RunSummary:
            calls.append(f"scrape:{need}")
            return RunSummary(
                run_id=f"r-{len(calls)}",
                source="linkedin_posts",
                query=need,
                status=scrape_status,
                leads_found=3,
                stored_new=2,
            )

    class FakeScore:
        def run(self) -> ScoreSummary:
            calls.append("score")
            return ScoreSummary(total=4, scored=4, by_category={PostCategory.CLIENT_LEAD.value: 3})

    class FakeEnrich:
        def run(self) -> EnrichSummary:
            calls.append("enrich")
            return EnrichSummary(total=4, with_company=2, with_email=1, with_website=1)

    monkeypatch.setattr(
        "leadforge.services.intent_scrape.build_intent_scrape_service",
        lambda source, settings: FakeScrape(),
    )
    monkeypatch.setattr(
        "leadforge.services.intent_score.build_intent_score_service",
        lambda settings, **kwargs: FakeScore(),
    )
    monkeypatch.setattr(
        "leadforge.services.intent_enrich.build_intent_enrich_service",
        lambda settings, **kwargs: FakeEnrich(),
    )


def _daily_env(tmp_path, monkeypatch, leads: list[IntentLead]) -> None:
    """Point DATABASE_URL / NEEDS_PATH / EXPORT_DIR at a throwaway sandbox."""
    db = tmp_path / "leads.db"
    _make_db(db, leads)
    needs_file = tmp_path / "needs.yaml"
    needs_file.write_text("needs:\n  - marketing agency\n  - SEO agency\n", encoding="utf-8")

    monkeypatch.delenv("SOURCES_ENABLED", raising=False)  # default enables linkedin_posts
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("NEEDS_PATH", str(needs_file))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    get_settings.cache_clear()


def test_daily_runs_every_stage_in_order_and_prints_summary(tmp_path, monkeypatch) -> None:
    # A fresh client lead, so the export step has something to write.
    _daily_env(tmp_path, monkeypatch, [_intent("Casey Lee", "casey_1", datetime.now(UTC))])
    calls: list[str] = []
    _stub_daily_services(monkeypatch, calls)

    result = runner.invoke(app, ["daily"])

    assert result.exit_code == 0, result.output
    # Every need scraped first, then score, then enrich — export is the CLI's own step.
    assert calls == ["scrape:marketing agency", "scrape:SEO agency", "score", "enrich"]
    # Each stage narrates itself, in order.
    steps = [result.output.index(f"[{n}/4]") for n in (1, 2, 3, 4)]
    assert steps == sorted(steps)
    # Closing summary: new leads (2 per need), client leads, and the file written.
    assert "Daily run complete." in result.output
    assert "new leads found    4" in result.output
    assert "client leads       3" in result.output
    exported = list((tmp_path / "exports").glob("intent_leads_*.xlsx"))
    assert len(exported) == 1
    assert str(exported[0].resolve()) in result.output


def test_daily_reports_when_no_client_leads_to_export(tmp_path, monkeypatch) -> None:
    _daily_env(tmp_path, monkeypatch, [])  # empty DB — nothing to export
    calls: list[str] = []
    _stub_daily_services(monkeypatch, calls)

    result = runner.invoke(app, ["daily"])

    assert result.exit_code == 0, result.output
    assert calls == ["scrape:marketing agency", "scrape:SEO agency", "score", "enrich"]
    assert "no client leads in 7 day(s)" in result.output


def test_daily_passes_its_options_through(tmp_path, monkeypatch) -> None:
    _daily_env(tmp_path, monkeypatch, [])
    seen: list[dict[str, object]] = []

    class FakeScrape:
        def run(self, *, need, since, limit, resume) -> RunSummary:
            seen.append({"since": since, "limit": limit})
            return RunSummary(run_id="r", source="linkedin_posts", query=need, status="completed")

    _stub_daily_services(monkeypatch, [])
    monkeypatch.setattr(
        "leadforge.services.intent_scrape.build_intent_scrape_service",
        lambda source, settings: FakeScrape(),
    )

    result = runner.invoke(app, ["daily", "--since", "30d", "--limit-per-need", "5"])

    assert result.exit_code == 0, result.output
    assert seen == [{"since": "30d", "limit": 5}] * 2


def test_daily_stops_scraping_on_compliance_abort(tmp_path, monkeypatch) -> None:
    _daily_env(tmp_path, monkeypatch, [])
    calls: list[str] = []
    _stub_daily_services(monkeypatch, calls, scrape_status="aborted")

    result = runner.invoke(app, ["daily"])

    # First need aborts the batch, but the remaining stages still run on what's stored.
    assert calls == ["scrape:marketing agency", "score", "enrich"]
    assert "Scraping stopped early" in result.output
    assert result.exit_code == 1
