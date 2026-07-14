"""Alembic migrations and the `leadforge init` command (README §7, §19)."""

from __future__ import annotations

from sqlalchemy import inspect
from typer.testing import CliRunner

from leadforge.cli.app import app
from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import create_db_engine
from leadforge.database.migrate import run_migrations

runner = CliRunner()

EXPECTED_TABLES = {"leads", "intent_leads", "rejects", "scrape_runs", "checkpoints"}


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
