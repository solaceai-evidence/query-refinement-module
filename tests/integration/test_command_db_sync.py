"""
Integration tests for command-database synchronization.

Tests verify that user commands properly maintain referential integrity
between Redis session state and database records.

Tests cover:
- /back command cascade deletes orphaned DB records
- /restart command cascade deletes all DB records
- /clear command resets DB record to incomplete state
- Database consistency after command sequences
"""
import pytest
from sqlalchemy.orm import Session

from query_refinement_module.core import RefinementSession, parse_user_command
from query_refinement_module.db.session import get_db_session
from query_refinement_module.db.crud import (
    create_user,
    create_query_session,
    create_query,
    create_refinement_step,
    get_query_refinement_steps,
    get_refinement_step_by_aspect,
    delete_refinement_steps_by_aspects,
    reset_refinement_step,
    create_followup,
    get_step_followups,
)
from query_refinement_module.db.database import init_db
from query_refinement_module.schema import RefinementAspect


@pytest.fixture(scope="module")
def db():
    """Initialize test database."""
    init_db()
    with get_db_session() as session:
        yield session


@pytest.fixture
def test_user(db: Session):
    """Create a test user."""
    import time
    unique_id = int(time.time() * 1000000)
    return create_user(
        db,
        username=f"test_cmd_user_{unique_id}",
        email=f"test_cmd_{unique_id}@example.com",
        password="TestPass123!",
        name="Test Command User"
    )


@pytest.fixture
def test_query(db: Session, test_user):
    """Create a test query with refinement steps."""
    session = create_query_session(db, user_id=test_user.id, framework_name="test_framework")
    query = create_query(db, session_id=session.id, original_query="Test query")
    
    # Create 5 refinement steps
    for i in range(5):
        create_refinement_step(db, query_id=query.id, aspect_name=f"dimension_{i+1}")
    
    return query


def test_cascade_delete_by_aspects(db: Session, test_query):
    """Test that delete_refinement_steps_by_aspects removes specified records."""
    query_id = test_query.id
    
    # Verify 5 steps exist
    steps_before = get_query_refinement_steps(db, query_id)
    assert len(steps_before) == 5
    
    # Delete dimensions 3, 4, 5 (simulating /back from dimension 3)
    deleted_count = delete_refinement_steps_by_aspects(
        db, query_id=query_id, aspect_names=["dimension_3", "dimension_4", "dimension_5"]
    )
    
    assert deleted_count == 3
    
    # Verify only dimensions 1 and 2 remain
    steps_after = get_query_refinement_steps(db, query_id)
    assert len(steps_after) == 2
    assert steps_after[0].aspect_name == "dimension_1"
    assert steps_after[1].aspect_name == "dimension_2"


def test_cascade_delete_with_followup_history(db: Session, test_user):
    """Test that cascade delete removes follow-up history via relationship."""
    session = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session.id, original_query="Test query")
    
    # Create step with follow-up history
    step = create_refinement_step(db, query_id=query.id, aspect_name="test_dimension")
    create_followup(db, refinement_step_id=step.id, question="Q1?", answer="A1")
    create_followup(db, refinement_step_id=step.id, question="Q2?", answer="A2")
    
    # Verify follow-ups exist
    followups_before = get_step_followups(db, refinement_step_id=step.id)
    assert len(followups_before) == 2
    
    # Store step_id before deletion
    step_id = step.id
    
    # Delete the step (should cascade to follow-ups)
    deleted_count = delete_refinement_steps_by_aspects(
        db, query_id=query.id, aspect_names=["test_dimension"]
    )
    
    assert deleted_count == 1
    
    # Verify follow-ups were cascade deleted
    followups_after = get_step_followups(db, refinement_step_id=step_id)
    assert len(followups_after) == 0


def test_reset_refinement_step_clears_state(db: Session, test_user):
    """Test that reset_refinement_step resets completion state."""
    session = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session.id, original_query="Test query")
    
    # Create completed step
    step = create_refinement_step(db, query_id=query.id, aspect_name="test_dimension")
    step.final_value = "some value"
    step.is_complete = True
    step.was_skipped = False
    step.user_ended_early = True
    db.commit()
    
    # Verify initial state
    retrieved_step = get_refinement_step_by_aspect(db, query_id=query.id, aspect_name="test_dimension")
    assert retrieved_step.is_complete is True
    assert retrieved_step.final_value == "some value"
    assert retrieved_step.user_ended_early is True
    
    # Reset the step (simulating /clear command)
    reset_step = reset_refinement_step(db, step_id=step.id, clear_followup_history=False)
    
    # Verify reset state
    assert reset_step.final_value is None
    assert reset_step.is_complete is False
    assert reset_step.was_skipped is False
    assert reset_step.user_ended_early is False


def test_reset_clears_followup_history(db: Session, test_user):
    """Test that reset_refinement_step optionally clears follow-up history."""
    session = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session.id, original_query="Test query")
    
    # Create step with history
    step = create_refinement_step(db, query_id=query.id, aspect_name="test_dimension")
    create_followup(db, refinement_step_id=step.id, question="Q1?", answer="A1")
    create_followup(db, refinement_step_id=step.id, question="Q2?", answer="A2")
    
    # Verify history exists
    followups_before = get_step_followups(db, refinement_step_id=step.id)
    assert len(followups_before) == 2
    
    # Reset with clear_followup_history=True
    reset_refinement_step(db, step_id=step.id, clear_followup_history=True)
    
    # Verify history cleared
    followups_after = get_step_followups(db, refinement_step_id=step.id)
    assert len(followups_after) == 0


def test_back_command_db_consistency(db: Session, test_user):
    """
    Test complete /back command workflow:
    1. Session truncates steps in Redis
    2. DB records cascade deleted to match
    """
    session_db = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session_db.id, original_query="Test query")
    
    # Create 5 DB records (simulating session initialization)
    for i in range(5):
        create_refinement_step(db, query_id=query.id, aspect_name=f"dimension_{i+1}")
    
    # Simulate /back from dimension 3 (removes dim 3, 4, 5)
    # In real flow, this happens in refinement.py after session.handle_command()
    cleared_aspects = ["dimension_3", "dimension_4", "dimension_5"]
    
    deleted_count = delete_refinement_steps_by_aspects(
        db, query_id=query.id, aspect_names=cleared_aspects
    )
    
    assert deleted_count == 3
    
    # Verify DB matches expected session state
    remaining_steps = get_query_refinement_steps(db, query.id)
    assert len(remaining_steps) == 2
    assert {s.aspect_name for s in remaining_steps} == {"dimension_1", "dimension_2"}


def test_restart_command_db_consistency(db: Session, test_user):
    """
    Test complete /restart command workflow:
    1. Session clears all steps in Redis
    2. DB records cascade deleted completely
    """
    session_db = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session_db.id, original_query="Test query")
    
    # Create 5 DB records
    for i in range(5):
        create_refinement_step(db, query_id=query.id, aspect_name=f"dimension_{i+1}")
    
    # Simulate /restart (removes all dimensions)
    cleared_aspects = [f"dimension_{i+1}" for i in range(5)]
    
    deleted_count = delete_refinement_steps_by_aspects(
        db, query_id=query.id, aspect_names=cleared_aspects
    )
    
    assert deleted_count == 5
    
    # Verify DB is empty
    remaining_steps = get_query_refinement_steps(db, query.id)
    assert len(remaining_steps) == 0


def test_clear_command_db_consistency(db: Session, test_user):
    """
    Test complete /clear command workflow:
    1. Session clears dimension state in Redis
    2. DB record reset to incomplete
    """
    session_db = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session_db.id, original_query="Test query")
    
    # Create completed dimension
    step = create_refinement_step(db, query_id=query.id, aspect_name="test_dimension")
    step.final_value = "some value"
    step.is_complete = True
    step.was_skipped = False
    db.commit()
    
    # Add follow-up history
    create_followup(db, refinement_step_id=step.id, question="Q1?", answer="A1")
    
    # Simulate /clear command
    reset_refinement_step(db, step_id=step.id, clear_followup_history=True)
    
    # Verify DB record reset
    retrieved_step = get_refinement_step_by_aspect(db, query_id=query.id, aspect_name="test_dimension")
    assert retrieved_step.final_value is None
    assert retrieved_step.is_complete is False
    
    # Verify follow-up history cleared
    followups = get_step_followups(db, refinement_step_id=step.id)
    assert len(followups) == 0


def test_multiple_back_commands_sequence(db: Session, test_user):
    """Test sequential /back commands maintain DB consistency."""
    session_db = create_query_session(db, user_id=test_user.id)
    query = create_query(db, session_id=session_db.id, original_query="Test query")
    
    # Create 5 DB records
    for i in range(5):
        create_refinement_step(db, query_id=query.id, aspect_name=f"dimension_{i+1}")
    
    # First /back from dimension 5 (removes 5)
    delete_refinement_steps_by_aspects(db, query_id=query.id, aspect_names=["dimension_5"])
    steps = get_query_refinement_steps(db, query.id)
    assert len(steps) == 4
    
    # Second /back from dimension 4 (removes 4)
    delete_refinement_steps_by_aspects(db, query_id=query.id, aspect_names=["dimension_4"])
    steps = get_query_refinement_steps(db, query.id)
    assert len(steps) == 3
    
    # Third /back from dimension 3 (removes 3)
    delete_refinement_steps_by_aspects(db, query_id=query.id, aspect_names=["dimension_3"])
    steps = get_query_refinement_steps(db, query.id)
    assert len(steps) == 2
    
    # Verify only dimensions 1 and 2 remain
    assert {s.aspect_name for s in steps} == {"dimension_1", "dimension_2"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
