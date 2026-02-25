"""add generated_question to refinement_steps

Revision ID: d4e1f2a3b5c6
Revises: c91f6a2e4d10
Create Date: 2026-02-24

Persists the last LLM-generated question for each refinement step so that
sessions can be restored after a server restart without triggering a new
LLM call for read-only commands (/steps, /status, /help).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e1f2a3b5c6'
down_revision = 'c91f6a2e4d10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'refinement_steps',
        sa.Column('generated_question', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('refinement_steps', 'generated_question')
