"""Add workflow limits and data consent fields

Revision ID: 4c9e8b2f1a3d
Revises: 39dbbd8d025d
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa

revision = '4c9e8b2f1a3d'
down_revision = ('39dbbd8d025d', 'a1b2c3d4e5f6')
branch_labels = None
depends_on = None


def upgrade():
    # Add user workflow constraint fields
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('has_completed_workflow', sa.Boolean(), nullable=False, server_default='0'))
    
    # Add query consent fields
    with op.batch_alter_table('queries') as batch_op:
        batch_op.add_column(sa.Column('consent_given', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('consent_given_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('has_completed_workflow')
        batch_op.drop_column('is_superuser')
    
    with op.batch_alter_table('queries') as batch_op:
        batch_op.drop_column('consent_given_at')
        batch_op.drop_column('consent_given')
