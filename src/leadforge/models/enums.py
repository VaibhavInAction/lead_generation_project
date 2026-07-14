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
