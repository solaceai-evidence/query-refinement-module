"""drop frontend logs table

Revision ID: 7f3c2a1b4d5e
Revises: f6e5d4c3b2a1
Create Date: 2026-07-10

Removes the legacy browser-log ingestion table now that the React frontend and
its frontend-log API surface have been retired in favor of the Chainlit-only web
interface.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f3c2a1b4d5e'
down_revision: Union[str, Sequence[str], None] = 'f6e5d4c3b2a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('frontend_logs'):
        op.drop_table('frontend_logs')


def downgrade() -> None:
    # Intentionally empty — restore via the original historical migration if needed.
    pass