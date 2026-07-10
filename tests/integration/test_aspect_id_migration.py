import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_ASPECT_ID_REVISION = "d4e1f2a3b5c6"
HEAD_REVISION = "7f3c2a1b4d5e"


def _run_alembic(db_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_aspect_id_migration_backfills_framework_specific_name(tmp_path):
    db_path = tmp_path / "aspect_id_backfill.sqlite"

    _run_alembic(db_path, PRE_ASPECT_ID_REVISION)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, email, name, password_hash, created_at, updated_at, is_superuser, has_completed_workflow) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, 0)",
        ("migration_user", "migration@example.com", "Migration User", "hash"),
    )
    user_id = cur.lastrowid
    cur.execute(
        "INSERT INTO query_sessions (user_id, started_at, status, framework_name) VALUES (?, CURRENT_TIMESTAMP, ?, ?)",
        (user_id, "active", "legal_research"),
    )
    session_id = cur.lastrowid
    cur.execute(
        "INSERT INTO queries (session_id, original_query, created_at, updated_at, consent_given) "
        "VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)",
        (session_id, "legacy legal research question"),
    )
    query_id = cur.lastrowid
    cur.execute(
        "INSERT INTO refinement_steps (query_id, aspect_name, final_value, is_complete, generated_question, was_skipped, user_ended_early, created_at) "
        "VALUES (?, ?, NULL, 0, ?, 0, 0, CURRENT_TIMESTAMP)",
        (query_id, "Parties and Relationships", "Who are the parties?"),
    )
    conn.commit()
    conn.close()

    _run_alembic(db_path, "head")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT aspect_name, aspect_id FROM refinement_steps")
    rows = cur.fetchall()
    cur.execute("SELECT version_num FROM alembic_version")
    versions = cur.fetchall()
    conn.close()

    assert rows == [("Parties and Relationships", "parties")]
    assert rows[0][1] != "parties_and_relationships"
    assert versions == [(HEAD_REVISION,)]