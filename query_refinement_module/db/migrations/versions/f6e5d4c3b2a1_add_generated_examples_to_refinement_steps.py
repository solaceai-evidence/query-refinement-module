"""add generated_examples to refinement_steps

Revision ID: f6e5d4c3b2a1
Revises: e3f7a1c9b2d5
Create Date: 2026-06-22

Persists the LLM-generated quick-reply examples for each refinement step alongside
the existing generated_question column, so that sessions restored after a server
restart can still expose structured clickable options without a new LLM call.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6e5d4c3b2a1'
down_revision = 'e3f7a1c9b2d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'refinement_steps',
        sa.Column('generated_examples', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('refinement_steps', 'generated_examples')
