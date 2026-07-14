"""Programmatic Alembic entry point used by ``leadforge init``.

Wrapping Alembic's command API here means the CLI never shells out to the
``alembic`` binary and migrations always run against the configured
``DATABASE_URL`` (README §7, §20) — one source of truth for the connection.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from leadforge.config.settings import Settings, get_settings
from leadforge.database.engine import ensure_database_parent

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_alembic_config(settings: Settings) -> Config:
    """Build an Alembic ``Config`` pointed at our migrations and DB URL."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def run_migrations(settings: Settings | None = None) -> None:
    """Upgrade the database to the latest revision (``head``).

    Ensures the SQLite parent directory exists first so a fresh checkout can
    ``init`` without a manual ``mkdir``.
    """
    settings = settings or get_settings()
    ensure_database_parent(settings.database_url)
    # The CLI narrates progress itself; keep Alembic's own INFO chatter off stderr.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    command.upgrade(make_alembic_config(settings), "head")
