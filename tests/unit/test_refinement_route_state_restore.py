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
            was_skipped=False,
            user_ended_early=False,
            followup_history=[],
        )
    ]

    _restore_session_from_db_state(session, db_steps)

    population_step = session.steps[0]
    assert population_step.is_complete is True
    assert population_step.normalized_value == ["adults", "COPD"]
