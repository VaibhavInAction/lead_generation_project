"""Lifecycle status enums for lead records.

Stored as strings (not native DB enums) so SQLite and PostgreSQL behave
identically and adding a status is a code change, not a migration.
"""

from __future__ import annotations

from enum import StrEnum


class LeadStatus(StrEnum):
    """Company `Lead` lifecycle (README §10)."""

    NEW = "new"
    ENRICHED = "enriched"
    SCORED = "scored"
    EXPORTED = "exported"


class IntentStatus(StrEnum):
    """`IntentLead` lifecycle (README §14) — no separate enrich stage."""

    NEW = "new"
    SCORED = "scored"
    EXPORTED = "exported"


class PostCategory(StrEnum):
    """What kind of post an `IntentLead` came from (README §14, Phase 9).

    The whole product hunts for *clients* — businesses seeking outside help — so
    everything else is noise and is filtered out by default. Only ``CLIENT_LEAD``
    is a genuine, first-person *request*; the other buckets name the specific way
    a post is junk, so we can review each class with ``--category``. As a
    `StrEnum`, each member *is* its lowercase string value, so it stores directly
    into a plain ``String`` column and compares equal to that literal.
    """

    CLIENT_LEAD = "client_lead"  # first-person request for outside help — KEEP
    JOB_POSTING = "job_posting"  # an employer hiring staff (full-time, apply now)
    CONTENT_NOISE = "content_noise"  # opinion/article-share/anecdote, not a request
    COMPETITOR_SELFPROMO = "competitor_selfpromo"  # an agency promoting itself
    RECRUITER_STAFFING = "recruiter_staffing"  # staffing a role to *join* an agency
    UNCLEAR = "unclear"  # no request signal and no clear junk signal

    @property
    def is_client(self) -> bool:
        """Whether this category is a genuine client lead (the only kind we keep)."""
        return self is PostCategory.CLIENT_LEAD
