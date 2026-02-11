"""add_feedback_metadata_json

Revision ID: 7b21b6c9a0f1
Revises: 12b1487a2bbe
Create Date: 2026-02-11

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b21b6c9a0f1"
down_revision: Union[str, Sequence[str], None] = "12b1487a2bbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add optional JSON metadata column to feedback."""
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table("feedback") as batch_op:
        batch_op.add_column(sa.Column("additional_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove feedback metadata column."""
    with op.batch_alter_table("feedback") as batch_op:
        batch_op.drop_column("additional_metadata")
