"""Add search expansion levels to queries

Revision ID: 2b4d6f8a9c10
Revises: 9c1e7f4a2b6d
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa


revision = "2b4d6f8a9c10"
down_revision = "9c1e7f4a2b6d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("queries") as batch_op:
        batch_op.add_column(sa.Column("search_expansion_levels", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("queries") as batch_op:
        batch_op.drop_column("search_expansion_levels")
