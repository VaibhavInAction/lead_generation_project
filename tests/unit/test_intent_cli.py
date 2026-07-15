"""CLI wiring for `leadforge intent scrape` / `intent list` (README §21)."""

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
