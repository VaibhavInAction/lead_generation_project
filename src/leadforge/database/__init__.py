"""leadforge.database — persistence, repositories, migrations (README §9).

The public surface of the data layer. Business logic imports repositories and
the session helpers from here; it never touches the ORM session directly or
writes SQL of its own (README §7).
"""

from __future__ import annotations

from leadforge.database.engine import (
    create_db_engine,
    create_session_factory,
    ensure_database_parent,
    session_scope,
)
from leadforge.database.migrate import run_migrations
from leadforge.database.repositories import (
    BaseRepository,
    CheckpointRepository,
    IntentLeadRepository,
    LeadRepository,
    RejectRepository,
    ScrapeRunRepository,
)

__all__ = [
    "BaseRepository",
    "CheckpointRepository",
    "IntentLeadRepository",
    "LeadRepository",
    "RejectRepository",
    "ScrapeRunRepository",
    "create_db_engine",
    "create_session_factory",
    "ensure_database_parent",
    "run_migrations",
    "session_scope",
]
