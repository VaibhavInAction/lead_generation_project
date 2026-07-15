"""intent_leads: category (client_lead | job_posting | unclear) (Phase 9)

Revision ID: d8e4a1b3c9f2
Revises: 72de0d2260ff
Create Date: 2026-07-15 10:12:44.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e4a1b3c9f2'
down_revision: str | None = '72de0d2260ff'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 9 adds post classification. `lead_score` / `freshness_score` already
    # exist from the initial schema, so only `category` is new. The server_default
    # backfills every existing row to 'unclear' (SQLite cannot add a NOT NULL
    # column to a populated table without one); new inserts use the ORM default.
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'category',
                sa.String(length=16),
                nullable=False,
                server_default='unclear',
            )
        )
        batch_op.create_index('ix_intent_leads_category', ['category'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('intent_leads', schema=None) as batch_op:
        batch_op.drop_index('ix_intent_leads_category')
        batch_op.drop_column('category')
