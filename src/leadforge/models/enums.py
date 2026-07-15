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
    hiring/recruitment posts are noise and get filtered out by default. As a
    `StrEnum`, each member *is* its lowercase string value, so it stores directly
    into a plain ``String`` column and compares equal to that literal.
    """

    CLIENT_LEAD = "client_lead"  # someone seeking an agency/freelancer — KEEP
    JOB_POSTING = "job_posting"  # an employer hiring staff — EXCLUDE by default
    UNCLEAR = "unclear"  # neither pattern matched clearly
