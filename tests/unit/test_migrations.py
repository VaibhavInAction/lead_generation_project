"""Alembic migrations and the `leadforge init` command (README §7, §19)."""

from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text
from typer.testing import CliRunner

from leadforge.cli.app import app
from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import create_db_engine
from leadforge.database.migrate import make_alembic_config, run_migrations

runner = CliRunner()

EXPECTED_TABLES = {"leads", "intent_leads", "rejects", "scrape_runs", "checkpoints"}

# The Phase-6 migration adds these to intent_leads.
_QUALITY_COLUMNS = {"data_quality_score", "quality_flags"}
_INITIAL_REVISION = "7e743ef52c9d"
# The Phase-9 migration adds the post-classification column.
_CATEGORY_COLUMN = "category"
_PRE_PHASE9_REVISION = "72de0d2260ff"
# The Phase-8 migration adds the enrichment columns.
_ENRICH_COLUMNS = {"contact_email", "website"}
_PRE_PHASE8_REVISION = "e5f6a7b8c9d0"


def test_run_migrations_creates_all_tables(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    run_migrations(settings)

    engine = create_db_engine(settings)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert EXPECTED_TABLES.issubset(tables)
    assert "alembic_version" in tables  # migrations actually stamped a revision


def test_run_migrations_is_idempotent(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    run_migrations(settings)
    run_migrations(settings)  # second run is a no-op, must not raise

    engine = create_db_engine(settings)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert EXPECTED_TABLES.issubset(tables)


def test_migrations_add_quality_columns(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    run_migrations(settings)

    engine = create_db_engine(settings)
    columns = {col["name"] for col in inspect(engine).get_columns("intent_leads")}
    engine.dispose()
    assert _QUALITY_COLUMNS.issubset(columns)


def test_quality_migration_backfills_existing_rows(tmp_path) -> None:
    """Upgrading a populated DB backfills the NOT NULL quality columns (server_default)."""
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    config = make_alembic_config(settings)

    command.upgrade(config, _INITIAL_REVISION)  # schema *before* Phase 6
    engine = create_db_engine(settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO intent_leads "
                "(id, author_name, need_text, need_category, post_url, post_text, "
                " platform, freshness_score, status, first_seen, last_updated) "
                "VALUES ('id1', 'Casey Lee', 'need', 'marketing', 'https://x/p/1', 'body', "
                " 'linkedin_public', 0, 'new', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    command.upgrade(config, "head")  # apply Phase 6 on the populated table

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT data_quality_score, quality_flags FROM intent_leads WHERE id='id1'")
        ).one()
    engine.dispose()
    assert row[0] == 0
    assert row[1] == "[]"


def test_migrations_add_category_column(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    run_migrations(settings)

    engine = create_db_engine(settings)
    columns = {col["name"] for col in inspect(engine).get_columns("intent_leads")}
    engine.dispose()
    assert _CATEGORY_COLUMN in columns


def test_category_migration_backfills_existing_rows(tmp_path) -> None:
    """Upgrading a populated DB backfills the NOT NULL category column to 'unclear'."""
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    config = make_alembic_config(settings)

    command.upgrade(config, _PRE_PHASE9_REVISION)  # schema *before* Phase 9
    engine = create_db_engine(settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO intent_leads "
                "(id, author_name, need_text, need_category, post_url, post_text, "
                " platform, freshness_score, data_quality_score, quality_flags, status, "
                " first_seen, last_updated) "
                "VALUES ('id1', 'Casey Lee', 'need', 'marketing', 'https://x/p/1', 'body', "
                " 'linkedin_public', 0, 0, '[]', 'new', "
                " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    command.upgrade(config, "head")  # apply Phase 9 on the populated table

    with engine.connect() as conn:
        category = conn.execute(
            text("SELECT category FROM intent_leads WHERE id='id1'")
        ).scalar_one()
    engine.dispose()
    assert category == "unclear"


def test_migrations_add_enrichment_columns(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    run_migrations(settings)

    engine = create_db_engine(settings)
    columns = {col["name"] for col in inspect(engine).get_columns("intent_leads")}
    engine.dispose()
    assert _ENRICH_COLUMNS.issubset(columns)


def test_enrichment_migration_backfills_existing_rows_to_null(tmp_path) -> None:
    """Upgrading a populated DB adds the nullable enrichment columns as NULL."""
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    config = make_alembic_config(settings)

    command.upgrade(config, _PRE_PHASE8_REVISION)  # schema *before* Phase 8
    engine = create_db_engine(settings)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO intent_leads "
                "(id, author_name, need_text, need_category, post_url, post_text, "
                " platform, freshness_score, data_quality_score, quality_flags, category, "
                " status, first_seen, last_updated) "
                "VALUES ('id1', 'Casey Lee', 'need', 'marketing', 'https://x/p/1', 'body', "
                " 'linkedin_public', 0, 0, '[]', 'unclear', 'new', "
                " '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    command.upgrade(config, "head")  # apply Phase 8 on the populated table

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT contact_email, website FROM intent_leads WHERE id='id1'")
        ).one()
    engine.dispose()
    assert row[0] is None
    assert row[1] is None


def test_init_command(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'leadforge.db'}")
    # get_settings is lru_cached; clear so the command reads our DATABASE_URL.
    get_settings.cache_clear()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert "database ready" in result.output
    for table in EXPECTED_TABLES:
        assert table in result.output
    # The SQLite parent dir is created for a fresh checkout.
    assert (tmp_path / "data" / "leadforge.db").exists()
