"""add_username_field_to_users

Revision ID: 2638f74414d0
Revises: 3d8d6c055e72
Create Date: 2025-12-16 10:08:41.390791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2638f74414d0'
down_revision: Union[str, Sequence[str], None] = '3d8d6c055e72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
    # with batch operations
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Add username column as nullable first
        batch_op.add_column(sa.Column('username', sa.String(length=50), nullable=True))
        # Create unique index on username
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)
    
    # For existing users, generate username from email (take part before @)
    # This SQL is SQLite-compatible
    op.execute("""
        UPDATE users 
        SET username = SUBSTR(email, 1, INSTR(email, '@') - 1)
        WHERE email IS NOT NULL AND username IS NULL
    """)
    
    # Now recreate the table with proper constraints using batch operations
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Make username non-nullable
        batch_op.alter_column('username', nullable=False, existing_type=sa.String(length=50))
        # Make email nullable
        batch_op.alter_column('email', nullable=True, existing_type=sa.String(length=255))


def downgrade() -> None:
    """Downgrade schema."""
    # SQLite doesn't support ALTER COLUMN, use batch operations
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Make email non-nullable again
        batch_op.alter_column('email', nullable=False, existing_type=sa.String(length=255))
        # Drop username index and column
        batch_op.drop_index(batch_op.f('ix_users_username'))
        batch_op.drop_column('username')
