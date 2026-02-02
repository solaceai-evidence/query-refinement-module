"""add_frontend_logs_table

Revision ID: 39dbbd8d025d
Revises: ec655e378a56
Create Date: 2026-01-14 15:50:38.774375

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39dbbd8d025d'
down_revision: Union[str, Sequence[str], None] = 'ec655e378a56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'frontend_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('client_timestamp', sa.DateTime(), nullable=True),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('log_type', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.String(length=36), nullable=True),
        sa.Column('trace_id', sa.String(length=36), nullable=True),
        sa.Column('url', sa.String(length=2048), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('screen_resolution', sa.String(length=50), nullable=True),
        sa.Column('viewport_size', sa.String(length=50), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('error_name', sa.String(length=200), nullable=True),
        sa.Column('error_stack', sa.Text(), nullable=True),
        sa.Column('error_line', sa.Integer(), nullable=True),
        sa.Column('error_column', sa.Integer(), nullable=True),
        sa.Column('error_file', sa.String(length=500), nullable=True),
        sa.Column('network_url', sa.String(length=2048), nullable=True),
        sa.Column('network_method', sa.String(length=10), nullable=True),
        sa.Column('network_status', sa.Integer(), nullable=True),
        sa.Column('network_duration_ms', sa.Integer(), nullable=True),
        sa.Column('performance_metric', sa.String(length=100), nullable=True),
        sa.Column('performance_value', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['query_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_frontend_logs_id'), 'frontend_logs', ['id'], unique=False)
    op.create_index(op.f('ix_frontend_logs_level'), 'frontend_logs', ['level'], unique=False)
    op.create_index(op.f('ix_frontend_logs_log_type'), 'frontend_logs', ['log_type'], unique=False)
    op.create_index(op.f('ix_frontend_logs_request_id'), 'frontend_logs', ['request_id'], unique=False)
    op.create_index(op.f('ix_frontend_logs_session_id'), 'frontend_logs', ['session_id'], unique=False)
    op.create_index(op.f('ix_frontend_logs_timestamp'), 'frontend_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_frontend_logs_trace_id'), 'frontend_logs', ['trace_id'], unique=False)
    op.create_index(op.f('ix_frontend_logs_user_id'), 'frontend_logs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_frontend_logs_user_id'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_trace_id'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_timestamp'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_session_id'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_request_id'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_log_type'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_level'), table_name='frontend_logs')
    op.drop_index(op.f('ix_frontend_logs_id'), table_name='frontend_logs')
    op.drop_table('frontend_logs')
