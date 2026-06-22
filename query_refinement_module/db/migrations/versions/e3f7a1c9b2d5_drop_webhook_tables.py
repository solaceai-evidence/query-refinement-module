"""drop webhook tables

Revision ID: e3f7a1c9b2d5
Revises: 2b4d6f8a9c10
Create Date: 2026-06-22

"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e3f7a1c9b2d5'
down_revision: Union[str, Sequence[str], None] = '2b4d6f8a9c10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop child table first (FK references webhooks.id)
    op.drop_table('webhook_deliveries')
    op.drop_table('webhooks')


def downgrade() -> None:
    # Intentionally empty — restore via original migration b5637a6b9fdb if needed.
    pass
