"""SQLAlchemy declarative base and shared column helpers.

The ORM lives in `models` (README §9): it owns the *shape* of a persisted
record and nothing else — no sessions, no queries, no business logic. The
`database` layer imports this metadata to build engines and migrations.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now — the single clock used for all provenance stamps."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base; `Base.metadata` is what Alembic and `create_all` target."""


class TimestampMixin:
    """`first_seen` / `last_updated` provenance carried by every lead record (README §10)."""

    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_updated: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
