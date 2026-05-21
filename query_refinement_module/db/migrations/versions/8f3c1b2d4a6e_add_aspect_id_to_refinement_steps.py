"""Add aspect_id to refinement_steps

Revision ID: 8f3c1b2d4a6e
Revises: d4e1f2a3b5c6
Create Date: 2026-05-07 12:20:00.000000

"""
from pathlib import Path
import re
from typing import Dict, Iterable, Tuple

from alembic import op
import sqlalchemy as sa
import yaml


# revision identifiers, used by Alembic.
revision = '8f3c1b2d4a6e'
down_revision = 'd4e1f2a3b5c6'
branch_labels = None
depends_on = None


def _slugify_aspect_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _iter_framework_documents() -> Iterable[Dict[str, object]]:
    base_dir = Path(__file__).resolve().parents[4] / 'refinement_frameworks'
    for framework_file in ('frameworks.yaml', 'copy_frameworks.yaml'):
        framework_path = base_dir / framework_file
        if not framework_path.exists():
            continue
        with framework_path.open('r', encoding='utf-8') as handle:
            document = yaml.safe_load(handle) or {}
        if isinstance(document, dict):
            yield document


def _load_framework_aspect_ids() -> Tuple[Dict[Tuple[str, str], str], Dict[str, str]]:
    by_framework_and_name: Dict[Tuple[str, str], str] = {}
    global_by_name: Dict[str, str] = {}
    ambiguous_names = set()

    for frameworks in _iter_framework_documents():
        for framework_name, entries in frameworks.items():
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                aspect_id = entry.get('id')
                aspect_name = entry.get('name')
                if not aspect_id or not aspect_name:
                    continue

                by_framework_and_name.setdefault((framework_name, aspect_name), aspect_id)

                existing = global_by_name.get(aspect_name)
                if existing is None:
                    global_by_name[aspect_name] = aspect_id
                elif existing != aspect_id:
                    ambiguous_names.add(aspect_name)

    for ambiguous_name in ambiguous_names:
        global_by_name.pop(ambiguous_name, None)

    return by_framework_and_name, global_by_name


def upgrade():
    with op.batch_alter_table('refinement_steps') as batch_op:
        batch_op.add_column(sa.Column('aspect_id', sa.Text(), nullable=True))

    connection = op.get_bind()
    by_framework_and_name, global_by_name = _load_framework_aspect_ids()

    rows = connection.execute(
        sa.text(
            """
            SELECT rs.id, rs.aspect_name, qs.framework_name
            FROM refinement_steps AS rs
            JOIN queries AS q ON q.id = rs.query_id
            JOIN query_sessions AS qs ON qs.id = q.session_id
            WHERE rs.aspect_id IS NULL
            """
        )
    ).fetchall()

    for row in rows:
        aspect_id = by_framework_and_name.get((row.framework_name, row.aspect_name))
        if aspect_id is None:
            aspect_id = global_by_name.get(row.aspect_name)
        if aspect_id is None:
            aspect_id = _slugify_aspect_name(row.aspect_name)

        connection.execute(
            sa.text(
                "UPDATE refinement_steps SET aspect_id = :aspect_id WHERE id = :step_id"
            ),
            {"aspect_id": aspect_id, "step_id": row.id},
        )


def downgrade():
    with op.batch_alter_table('refinement_steps') as batch_op:
        batch_op.drop_column('aspect_id')