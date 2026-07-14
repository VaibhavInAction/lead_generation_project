"""Alembic environment — wires migrations to LeadForge's models and settings.

The connection URL comes from ``DATABASE_URL`` via :class:`Settings` (README §20),
falling back to whatever the caller set on the Alembic config (the programmatic
runner does). Target metadata is the shared declarative ``Base`` so
``--autogenerate`` sees every model.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# `leadforge.models.orm` is imported for its side effect: registering every
# table on Base.metadata so autogenerate and create-from-metadata see them.
import leadforge.models.orm  # noqa: F401
from leadforge.config.settings import Settings
from leadforge.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Prefer an explicitly configured URL (set by the runner); else settings."""
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Batch mode lets SQLite apply ALTERs later phases will need.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
