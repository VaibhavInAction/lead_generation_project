"""Pydantic schemas for the scraper boundary (README §7, §12).

``RawLead`` is the *dumb* output every scraper produces: source-specific raw
key/values, not yet validated or normalized. The validation layer (Phase 6)
turns these into typed ``Lead`` / ``IntentLead`` records — keeping the type
boundary in exactly one place. ``SearchQuery`` is the input to ``discover()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from leadforge.models.base import utcnow


class SearchQuery(BaseModel):
    """A discovery request: what need to mine for, and how fresh (README §13.1)."""

    model_config = ConfigDict(frozen=True)

    need: str  # e.g. "marketing", "video editor"
    since: str = "7d"  # recency window: 7d | 30d | ... (mapped to search-engine filters)
    limit: int | None = None  # max candidate URLs to yield, None = source default


class RawLead(BaseModel):
    """Raw, un-validated extraction from one page (README §12).

    ``data`` holds source-specific fields as-is; the validation layer decides
    what they mean. Scrapers never construct ORM rows — that keeps them ignorant
    of the database (README §9).
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)
