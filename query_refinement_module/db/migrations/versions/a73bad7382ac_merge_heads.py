"""merge heads

Revision ID: a73bad7382ac
Revises: 7b21b6c9a0f1, b5637a6b9fdb
Create Date: 2026-02-12 08:23:52.243179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a73bad7382ac'
down_revision: Union[str, Sequence[str], None] = ('7b21b6c9a0f1', 'b5637a6b9fdb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
