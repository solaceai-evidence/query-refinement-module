"""Add evaluation storage fields for refinement_steps and queries

Per-dimension storage (refinement_steps):
- final_value: The refined value (only persisted data, no conversation)
- is_complete, was_skipped: Status flags

Per-session storage (queries):
- All fields from QueryRefinementResponse Pydantic model
- synthesized_statement, refined_dimensions, search_optimized, etc.

Revision ID: a1b2c3d4e5f6
Revises: 12b1487a2bbe
Create Date: 2026-01-28 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '12b1487a2bbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add evaluation storage fields."""
    # =========================================================================
    # Per-dimension: refinement_steps table
    # =========================================================================
    
    # Final refined value (only persisted data - no conversation)
    op.add_column('refinement_steps', sa.Column('final_value', sa.Text(), nullable=True))
    
    # Status flags
    op.add_column('refinement_steps', sa.Column('is_complete', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('refinement_steps', sa.Column('was_skipped', sa.Boolean(), nullable=False, server_default='0'))
    
    # Evaluation-only: User used /done before LLM said is_complete=True
    op.add_column('refinement_steps', sa.Column('user_ended_early', sa.Boolean(), nullable=False, server_default='0'))
    
    # =========================================================================
    # Per-session: queries table (QueryRefinementResponse fields)
    # =========================================================================
    
    # Completion timestamp
    op.add_column('queries', sa.Column('completed_at', sa.DateTime(), nullable=True))
    
    # Synthesized research statement
    op.add_column('queries', sa.Column('synthesized_statement', sa.Text(), nullable=True))
    
    # Normalized dimension values {dimension_id: value}
    op.add_column('queries', sa.Column('refined_dimensions', sa.JSON(), nullable=True))
    
    # Search optimization (semantic, keyword, grey_literature)
    op.add_column('queries', sa.Column('search_optimized', sa.JSON(), nullable=True))
    
    # Search filters (publication_years, venues, authors, etc.)
    op.add_column('queries', sa.Column('search_filters', sa.JSON(), nullable=True))
    
    # Terminology (primary_terms, synonyms, domain_specific, colloquial)
    op.add_column('queries', sa.Column('terminology', sa.JSON(), nullable=True))
    
    # Metadata (temporal, geographic, source_types, other)
    op.add_column('queries', sa.Column('response_metadata', sa.JSON(), nullable=True))
    
    # Processing log (preserved, normalized, integrated, expanded)
    op.add_column('queries', sa.Column('processing_log', sa.JSON(), nullable=True))
    
    # Note: We keep followup_history table for backward compatibility
    # but stop writing to it for new sessions


def downgrade() -> None:
    """Remove evaluation storage fields."""
    # Queries table
    op.drop_column('queries', 'processing_log')
    op.drop_column('queries', 'response_metadata')
    op.drop_column('queries', 'terminology')
    op.drop_column('queries', 'search_filters')
    op.drop_column('queries', 'search_optimized')
    op.drop_column('queries', 'refined_dimensions')
    op.drop_column('queries', 'synthesized_statement')
    op.drop_column('queries', 'completed_at')
    
    # Refinement steps table
    op.drop_column('refinement_steps', 'user_ended_early')
    op.drop_column('refinement_steps', 'was_skipped')
    op.drop_column('refinement_steps', 'is_complete')
    op.drop_column('refinement_steps', 'final_value')
