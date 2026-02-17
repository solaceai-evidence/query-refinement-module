"""add_user_framework_access_table

Revision ID: c91f6a2e4d10
Revises: a73bad7382ac
Create Date: 2026-02-17 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c91f6a2e4d10'
down_revision: Union[str, Sequence[str], None] = 'a73bad7382ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_framework_access',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('framework_name', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'framework_name', name='uq_user_framework_access_user_framework'),
    )
    op.create_index(op.f('ix_user_framework_access_user_id'), 'user_framework_access', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_framework_access_framework_name'), 'user_framework_access', ['framework_name'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_framework_access_framework_name'), table_name='user_framework_access')
    op.drop_index(op.f('ix_user_framework_access_user_id'), table_name='user_framework_access')
    op.drop_table('user_framework_access')
