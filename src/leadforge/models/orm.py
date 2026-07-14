"""SQLAlchemy 2 ORM models — the persisted shape of every LeadForge record.

Two lead entities plus three operational tables:

* :class:`Lead`       — a company profile (README §10).
* :class:`IntentLead` — a person/company with a publicly stated need (README §14);
  links back to a :class:`Lead` when the author's company is resolvable.
* :class:`Reject`     — rows that failed validation, kept with a reason (README §8):
  rejects are never silently dropped.
* :class:`ScrapeRun`  — per-run audit metadata: counts, errors, duration (README §12).
* :class:`Checkpoint` — resume state per source/query so interrupted runs continue (README §8).

List-valued fields (keywords, tech_stack, …) use JSON columns — portable across
SQLite and PostgreSQL and adequate for the read-mostly access this data sees.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadforge.models.base import Base, TimestampMixin, utcnow
from leadforge.models.enums import IntentStatus, LeadStatus


def _new_id() -> str:
    """Fresh UUID4 as a string — stable across SQLite (no native UUID) and PostgreSQL."""
    return str(uuid4())


class Lead(Base, TimestampMixin):
    """A business profile discovered from a public source (README §10)."""

    __tablename__ = "leads"

    # Identity
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    business_name: Mapped[str] = mapped_column(String(512))
    website: Mapped[str | None] = mapped_column(String(1024), default=None)
    domain: Mapped[str | None] = mapped_column(String(255), default=None)  # canonical dedup key

    # Classification
    industry: Mapped[str | None] = mapped_column(String(255), default=None)
    category: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    products: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Location
    country: Mapped[str | None] = mapped_column(String(128), default=None)
    state: Mapped[str | None] = mapped_column(String(128), default=None)
    city: Mapped[str | None] = mapped_column(String(128), default=None)
    postal_code: Mapped[str | None] = mapped_column(String(32), default=None)

    # Contact (public/business only)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)  # E.164
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    linkedin_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    instagram: Mapped[str | None] = mapped_column(String(255), default=None)
    facebook: Mapped[str | None] = mapped_column(String(255), default=None)
    twitter: Mapped[str | None] = mapped_column(String(255), default=None)

    # Firmographics (public info only)
    company_size: Mapped[str | None] = mapped_column(String(32), default=None)
    employee_count_est: Mapped[int | None] = mapped_column(Integer, default=None)
    founder: Mapped[str | None] = mapped_column(String(255), default=None)
    ceo: Mapped[str | None] = mapped_column(String(255), default=None)
    google_rating: Mapped[float | None] = mapped_column(Float, default=None)
    review_count: Mapped[int | None] = mapped_column(Integer, default=None)
    business_hours: Mapped[str | None] = mapped_column(String(512), default=None)
    tech_stack: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Provenance & quality — every record, always
    lead_source: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(String(1024))
    data_quality_score: Mapped[int] = mapped_column(Integer, default=0)  # 0–100
    lead_score: Mapped[int | None] = mapped_column(Integer, default=None)  # 0–100, ICP fit
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False, length=16), default=LeadStatus.NEW
    )

    # Intent leads whose author resolved to this company.
    intent_leads: Mapped[list[IntentLead]] = relationship(back_populates="lead")

    __table_args__ = (
        Index("ix_leads_domain", "domain"),
        Index("ix_leads_source_url", "source_url"),
        Index("ix_leads_status", "status"),
    )

    def __repr__(self) -> str:
        return f"Lead(id={self.id!r}, business_name={self.business_name!r})"


class IntentLead(Base, TimestampMixin):
    """A publicly stated need with an author and a timestamp (README §14)."""

    __tablename__ = "intent_leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)

    # Who posted
    author_name: Mapped[str] = mapped_column(String(255))
    author_profile_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    author_headline: Mapped[str | None] = mapped_column(String(512), default=None)
    company: Mapped[str | None] = mapped_column(String(255), default=None)

    # What they need
    need_text: Mapped[str] = mapped_column(Text)
    # taxonomy: video_editing | marketing | web_dev | design | ...
    need_category: Mapped[str] = mapped_column(String(64))
    post_url: Mapped[str] = mapped_column(String(1024), unique=True)  # dedup key
    post_text: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(default=None)
    platform: Mapped[str] = mapped_column(String(32))  # reddit | linkedin_public | job_board

    # Actionability
    freshness_score: Mapped[int] = mapped_column(Integer, default=0)  # 0–100, decays fast
    lead_score: Mapped[int | None] = mapped_column(Integer, default=None)
    suggested_angle: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[IntentStatus] = mapped_column(
        Enum(IntentStatus, native_enum=False, length=16), default=IntentStatus.NEW
    )

    # Link back to a company Lead when the author's company is resolvable (README §14).
    lead_id: Mapped[str | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), default=None
    )
    lead: Mapped[Lead | None] = relationship(back_populates="intent_leads")

    __table_args__ = (
        Index("ix_intent_leads_platform", "platform"),
        Index("ix_intent_leads_need_category", "need_category"),
        Index("ix_intent_leads_status", "status"),
    )

    def __repr__(self) -> str:
        return f"IntentLead(id={self.id!r}, author_name={self.author_name!r})"


class Reject(Base):
    """A row that failed validation, kept with its reason — never silently dropped (README §8)."""

    __tablename__ = "rejects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))  # where it failed: validation | dedup | …
    reason: Mapped[str] = mapped_column(Text)
    raw_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    source_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_rejects_source", "source"),)

    def __repr__(self) -> str:
        return f"Reject(id={self.id!r}, stage={self.stage!r}, reason={self.reason!r})"


class ScrapeRun(Base):
    """Per-run audit metadata: query, counts, errors, duration (README §12)."""

    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    run_id: Mapped[str] = mapped_column(String(64), unique=True)  # correlates with logs
    source: Mapped[str] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(String(1024), default=None)
    # running | completed | aborted
    status: Mapped[str] = mapped_column(String(32), default="running")

    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    leads_found: Mapped[int] = mapped_column(Integer, default=0)
    rejects: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_seconds: Mapped[float | None] = mapped_column(Float, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (Index("ix_scrape_runs_source", "source"),)

    def __repr__(self) -> str:
        return f"ScrapeRun(run_id={self.run_id!r}, source={self.source!r}, status={self.status!r})"


class Checkpoint(Base):
    """Resume state per (source, query) so an interrupted run continues (README §8)."""

    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(String(1024), default="")
    state: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)  # last page, seen URLs, …
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("uq_checkpoints_source_query", "source", "query", unique=True),)

    def __repr__(self) -> str:
        return f"Checkpoint(source={self.source!r}, query={self.query!r})"
