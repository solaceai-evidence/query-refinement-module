from types import SimpleNamespace

from query_refinement_module.core import RefinementSession
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.api.routes.refinement import _restore_session_from_db_state


def _make_session() -> RefinementSession:
    session = RefinementSession(original_query="COPD therapy query")
    session.add_step(
        RefinementAspect(
            id="population",
            name="Population",
            description="Target population",
            specifications="Analyze {query}",
        )
    )
    session.add_step(
        RefinementAspect(
            id="intervention",
            name="Intervention",
            description="Target intervention",
            specifications="Analyze {query}",
        )
    )
    return session


def test_restore_session_keeps_partial_done_value_without_followups():
    session = _make_session()

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value="adults with COPD",
            is_complete=True,
            was_skipped=False,
            user_ended_early=True,
            followup_history=[],
            generated_question=None,
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.is_complete is True
    assert population_step.was_skipped is False
    assert population_step.normalized_value_as_str == "adults with COPD"


def test_restore_session_preserves_skipped_with_no_value():
    session = _make_session()

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value=None,
            is_complete=False,
            was_skipped=True,
            user_ended_early=False,
            followup_history=[],
            generated_question=None,
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.is_complete is True
    assert population_step.was_skipped is True
    assert population_step.normalized_value is None


def test_restore_session_deserializes_json_final_value():
    session = _make_session()

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value='["adults", "COPD"]',
            is_complete=True,
            generated_question=None,
            was_skipped=False,
            user_ended_early=False,
            followup_history=[],
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.is_complete is True
    assert population_step.normalized_value == ["adults", "COPD"]


def test_restore_session_restores_generated_question_for_active_step():
    """generated_question is restored into follow_up_question when there is no followup history."""
    session = _make_session()

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value=None,
            is_complete=False,
            was_skipped=False,
            user_ended_early=False,
            followup_history=[],
            generated_question="What is the target population for your query?",
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.follow_up_question == "What is the target population for your query?"


def test_restore_session_no_generated_question_leaves_followup_question_unset():
    """When generated_question is None and there are no followups, follow_up_question stays unset."""
    session = _make_session()

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value=None,
            is_complete=False,
            was_skipped=False,
            user_ended_early=False,
            followup_history=[],
            generated_question=None,
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.follow_up_question is None


def test_generated_question_takes_priority_over_followup_history():
    """generated_question always wins: it holds the most recent LLM-issued question.

    When followup history exists AND generated_question is set, the latter is
    the active (possibly unanswered) question and must be restored so the user
    is not shown a stale prompt that has already been answered.
    """
    session = _make_session()

    last_followup = SimpleNamespace(question="Answered followup question?", answer="adults")

    db_steps = [
        SimpleNamespace(
            aspect_name="Population",
            final_value="adults",
            is_complete=True,
            was_skipped=False,
            user_ended_early=False,
            followup_history=[last_followup],
            generated_question="This is the current active question",
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.follow_up_question == "This is the current active question"
