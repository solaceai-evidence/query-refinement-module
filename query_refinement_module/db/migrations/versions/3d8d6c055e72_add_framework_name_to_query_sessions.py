"""add_framework_name_to_query_sessions

Revision ID: 3d8d6c055e72
Revises: f02d0f7a5296
Create Date: 2025-12-02 12:00:56.615825

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d8d6c055e72'
down_revision: Union[str, Sequence[str], None] = 'f02d0f7a5296'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('query_sessions', sa.Column('framework_name', sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('query_sessions', 'framework_name')
