"""Rename query synthesis columns to canonical names

Revision ID: 9c1e7f4a2b6d
Revises: 8f3c1b2d4a6e
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa


revision = "9c1e7f4a2b6d"
down_revision = "8f3c1b2d4a6e"
branch_labels = None
depends_on = None


def _queries_table(use_canonical_names: bool) -> sa.Table:
    metadata = sa.MetaData()
    sa.Table("query_sessions", metadata, sa.Column("id", sa.Integer))

    statement_column = "integrated_statement" if use_canonical_names else "synthesized_statement"
    dimensions_column = "dimensions_specifications" if use_canonical_names else "refined_dimensions"
    metadata_column = "metadata" if use_canonical_names else "response_metadata"

    return sa.Table(
        "queries",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("query_sessions.id"), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("refined_query", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("consent_given_at", sa.DateTime(), nullable=True),
        sa.Column(statement_column, sa.Text(), nullable=True),
        sa.Column(dimensions_column, sa.JSON(), nullable=True),
        sa.Column("search_optimized", sa.JSON(), nullable=True),
        sa.Column("search_filters", sa.JSON(), nullable=True),
        sa.Column("terminology", sa.JSON(), nullable=True),
        sa.Column(metadata_column, sa.JSON(), nullable=True),
        sa.Column("processing_log", sa.JSON(), nullable=True),
    )


def upgrade():
    with op.batch_alter_table("queries", copy_from=_queries_table(use_canonical_names=False)) as batch_op:
        batch_op.alter_column(
            "synthesized_statement",
            new_column_name="integrated_statement",
            existing_type=sa.Text(),
            nullable=True,
        )
        batch_op.alter_column(
            "refined_dimensions",
            new_column_name="dimensions_specifications",
            existing_type=sa.JSON(),
            nullable=True,
        )
        batch_op.alter_column(
            "response_metadata",
            new_column_name="metadata",
            existing_type=sa.JSON(),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table("queries", copy_from=_queries_table(use_canonical_names=True)) as batch_op:
        batch_op.alter_column(
            "metadata",
            new_column_name="response_metadata",
            existing_type=sa.JSON(),
            nullable=True,
        )
        batch_op.alter_column(
            "dimensions_specifications",
            new_column_name="refined_dimensions",
            existing_type=sa.JSON(),
            nullable=True,
        )
        batch_op.alter_column(
            "integrated_statement",
            new_column_name="synthesized_statement",
            existing_type=sa.Text(),
            nullable=True,
        )