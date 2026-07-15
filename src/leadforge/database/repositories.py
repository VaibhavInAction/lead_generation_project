"""Repository pattern — the *only* place SQL is written (README §7).

No raw queries live outside this module: services and the CLI ask repositories
for objects, so swapping SQLite for PostgreSQL never touches call sites. Each
repository is constructed with a :class:`~sqlalchemy.orm.Session` (dependency
injection, README §24) and never opens or commits transactions itself — that is
the caller's unit of work (see :func:`leadforge.database.engine.session_scope`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from leadforge.models.base import Base
from leadforge.models.orm import Checkpoint, IntentLead, Lead, Reject, ScrapeRun

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Common CRUD shared by every repository, typed to one model."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, obj: ModelT) -> ModelT:
        """Stage ``obj`` for insert and flush so DB-side defaults are populated."""
        self.session.add(obj)
        self.session.flush()
        return obj

    def get(self, obj_id: str) -> ModelT | None:
        """Fetch one row by primary key, or ``None`` if absent."""
        return self.session.get(self.model, obj_id)

    def list(self, *, limit: int | None = None, offset: int = 0) -> list[ModelT]:
        """Return rows, optionally paginated. Newest-first ordering is per-repo."""
        stmt = select(self.model).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def count(self) -> int:
        """Total number of rows for this model."""
        return self.session.scalar(select(func.count()).select_from(self.model)) or 0

    def delete(self, obj: ModelT) -> None:
        """Mark ``obj`` for deletion (flushed with the surrounding transaction)."""
        self.session.delete(obj)
        self.session.flush()


class LeadRepository(BaseRepository[Lead]):
    """Persistence for company leads, keyed for dedup by domain / source URL (README §17)."""

    model = Lead

    def get_by_domain(self, domain: str) -> Lead | None:
        """Strongest dedup key: same registered domain ⇒ same company (README §17)."""
        return self.session.scalars(select(Lead).where(Lead.domain == domain)).first()

    def get_by_source_url(self, source_url: str) -> Lead | None:
        """Look up by provenance URL — used to detect a re-scrape of the same page."""
        return self.session.scalars(select(Lead).where(Lead.source_url == source_url)).first()


class IntentLeadRepository(BaseRepository[IntentLead]):
    """Persistence for intent leads; ``post_url`` is the dedup key (README §14)."""

    model = IntentLead

    def get_by_post_url(self, post_url: str) -> IntentLead | None:
        """Dedup lookup: an intent lead is unique by the post it came from (README §14)."""
        return self.session.scalars(
            select(IntentLead).where(IntentLead.post_url == post_url)
        ).first()

    def list_recent(self, *, limit: int | None = None) -> list[IntentLead]:
        """Intent leads ordered most recently captured first (by ``first_seen``)."""
        stmt = select(IntentLead).order_by(IntentLead.first_seen.desc(), IntentLead.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def _ranked_stmt(
        self, *, category: str | None = None, newer_than: datetime | None = None
    ) -> Select[tuple[IntentLead]]:
        """Filter (category / recency) shared by :meth:`list_ranked` and :meth:`count_ranked`.

        Recency uses ``posted_at`` when known, else ``first_seen`` — the same
        fallback the freshness scorer uses (README §14), so a post with no
        timestamp is aged from when we first saw it, not silently kept forever.
        """
        stmt = select(IntentLead)
        if category is not None:
            stmt = stmt.where(IntentLead.category == category)
        if newer_than is not None:
            effective = func.coalesce(IntentLead.posted_at, IntentLead.first_seen)
            stmt = stmt.where(effective >= newer_than)
        return stmt

    def list_ranked(
        self,
        *,
        category: str | None = None,
        newer_than: datetime | None = None,
        limit: int | None = None,
    ) -> list[IntentLead]:
        """Intent leads ranked by ``lead_score`` desc (Phase 9, README §16).

        Unscored rows (``lead_score`` NULL) sort last under SQLite's DESC nulls-last
        ordering; ties break by most-recent-first. Optionally filtered to one
        ``category`` and to posts newer than ``newer_than``.
        """
        stmt = self._ranked_stmt(category=category, newer_than=newer_than).order_by(
            IntentLead.lead_score.desc(), IntentLead.first_seen.desc(), IntentLead.id
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def count_ranked(
        self, *, category: str | None = None, newer_than: datetime | None = None
    ) -> int:
        """Count intent leads matching the same filters as :meth:`list_ranked`."""
        stmt = self._ranked_stmt(category=category, newer_than=newer_than)
        return self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    def upsert_by_post_url(self, lead: IntentLead) -> IntentLead:
        """Insert a new intent lead, or refresh the existing one for this ``post_url``.

        Dedup-on-write (README §8): a post already seen is updated in place rather
        than duplicated, preserving its original ``first_seen`` provenance.
        """
        existing = self.get_by_post_url(lead.post_url)
        if existing is None:
            return self.add(lead)

        # Merge incoming values onto the existing row. `id`/`first_seen` are
        # provenance and never change; `last_updated` is refreshed by onupdate.
        # A ``None`` on the incoming record means "not extracted", so it never
        # overwrites a filled field — this both preserves lifecycle/score columns
        # a re-scrape doesn't set and honors the merge rule in README §17.
        preserved = {"id", "first_seen", "last_updated"}
        for column in IntentLead.__table__.columns:
            if column.name in preserved:
                continue
            value = getattr(lead, column.name)
            if value is not None:
                setattr(existing, column.name, value)
        self.session.flush()
        return existing


class RejectRepository(BaseRepository[Reject]):
    """Persistence for rejected rows — auditability, never silent drops (README §8)."""

    model = Reject


class ScrapeRunRepository(BaseRepository[ScrapeRun]):
    """Persistence for run audit records (README §12)."""

    model = ScrapeRun

    def get_by_run_id(self, run_id: str) -> ScrapeRun | None:
        """Fetch a run by its structlog-correlated ``run_id``."""
        return self.session.scalars(select(ScrapeRun).where(ScrapeRun.run_id == run_id)).first()

    def requests_since(self, source: str, since: datetime) -> int:
        """Total requests (``pages_visited``) a source has spent since ``since``.

        Backs the *daily* request cap (README §6): summing today's runs makes the
        ceiling genuinely per-day, not merely per-run.
        """
        stmt = (
            select(func.coalesce(func.sum(ScrapeRun.pages_visited), 0))
            .where(ScrapeRun.source == source)
            .where(ScrapeRun.started_at >= since)
        )
        return self.session.scalar(stmt) or 0


class CheckpointRepository(BaseRepository[Checkpoint]):
    """Resume state per (source, query) so interrupted runs continue (README §8)."""

    model = Checkpoint

    def get_for(self, source: str, query: str = "") -> Checkpoint | None:
        """Fetch the checkpoint for a source/query pair, if one exists."""
        return self.session.scalars(
            select(Checkpoint).where(Checkpoint.source == source, Checkpoint.query == query)
        ).first()

    def save(self, source: str, state: dict[str, object], query: str = "") -> Checkpoint:
        """Create or update the checkpoint for a source/query pair."""
        existing = self.get_for(source, query)
        if existing is None:
            return self.add(Checkpoint(source=source, query=query, state=state))
        existing.state = state
        self.session.flush()
        return existing
