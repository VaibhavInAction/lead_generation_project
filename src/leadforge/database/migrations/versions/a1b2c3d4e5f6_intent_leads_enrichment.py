"""intent_leads: contact_email + website enrichment (Phase 8)

Revision ID: a1b2c3d4e5f6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 09:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 8 enrichment adds two optional contact facts. `company` already exists
    # from the initial schema, so only these two are new. Both are nullable, so
    # existing rows backfill to NULL with no server_default; `leadforge intent
    # enrich` fills them in on demand from each post's text.
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contact_email', sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column('website', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.drop_column('website')
        batch_op.drop_column('contact_email')
