"""Engine and session factory — the one place a connection is opened.

Isolating construction here is what makes SQLite → PostgreSQL a config change
(README §7): callers ask for a session, never for a driver.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from leadforge.config.settings import Settings, get_settings

_SQLITE_PREFIX = "sqlite:///"


def _sqlite_file(database_url: str) -> Path | None:
    """Return the on-disk path for a file-backed SQLite URL, else ``None``.

    In-memory (``sqlite:///:memory:``) and non-SQLite URLs have no directory to
    create, so they return ``None``.
    """
    if not database_url.startswith(_SQLITE_PREFIX):
        return None
    tail = database_url[len(_SQLITE_PREFIX) :]
    if not tail or tail == ":memory:":
        return None
    return Path(tail)


def ensure_database_parent(database_url: str) -> None:
    """Create the parent directory of a file-backed SQLite DB (e.g. ``data/``).

    A no-op for in-memory or networked databases.
    """
    path = _sqlite_file(database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Build an :class:`~sqlalchemy.Engine` from settings.

    For SQLite, foreign-key enforcement is enabled per-connection (off by
    default in SQLite) so ``ON DELETE`` behaviour matches PostgreSQL.
    """
    settings = settings or get_settings()
    ensure_database_parent(settings.database_url)
    engine = create_engine(settings.database_url, future=True)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a configured ``sessionmaker`` bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional session context: commit on success, roll back on error.

    The unit of work for a service call — repositories receive the yielded
    session and never manage transactions themselves.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
