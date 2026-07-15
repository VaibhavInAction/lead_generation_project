"""intent_leads: widen category for richer post classes (Phase 9)

Revision ID: e5f6a7b8c9d0
Revises: d8e4a1b3c9f2
Create Date: 2026-07-15 12:40:10.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd8e4a1b3c9f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The classifier now emits longer category values (competitor_selfpromo = 20
    # chars, recruiter_staffing = 18) that overflow the original VARCHAR(16). SQLite
    # ignores VARCHAR length, but widen the declared type to 32 so the schema matches
    # the ORM and stays correct on PostgreSQL. No data migration: existing rows keep
    # their value ('unclear' or the old client_lead/job_posting) and are re-labeled
    # the next time `leadforge intent score` runs.
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.alter_column(
            'category',
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
            existing_server_default='unclear',
        )


def downgrade() -> None:
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.alter_column(
            'category',
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
            existing_server_default='unclear',
        )
