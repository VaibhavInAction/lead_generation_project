"""leadforge.models — the persisted shape of a record (README §9, §10, §14).

Owns SQLAlchemy ORM models and lifecycle enums; knows nothing about sessions,
queries, scraping, or export formats. The `database` layer builds on this.
"""

from __future__ import annotations

from leadforge.models.base import Base, TimestampMixin, utcnow
from leadforge.models.enums import IntentStatus, LeadStatus
from leadforge.models.orm import Checkpoint, IntentLead, Lead, Reject, ScrapeRun

__all__ = [
    "Base",
    "Checkpoint",
    "IntentLead",
    "IntentStatus",
    "Lead",
    "LeadStatus",
    "Reject",
    "ScrapeRun",
    "TimestampMixin",
    "utcnow",
]
