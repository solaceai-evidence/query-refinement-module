"""Tests for the Chainlit adapter, survey model and chat formatting helpers."""

from types import SimpleNamespace

import pytest

import query_refinement_module.application.chainlit_adapter as adapter_module
from query_refinement_module.api.exceptions import ResourceNotFoundError
from query_refinement_module.application.chainlit_adapter import ChainlitRefinementAdapter
from query_refinement_module.application.feedback_survey import SurveyResponses, survey_items
from query_refinement_module.chainlit_app import (
    build_markdown_export,
    format_prompt,
    render_concept_blocks,
    render_synthesis_markdown,
    task_state,
)
from query_refinement_module.db.crud import (
    assign_user_framework_access,
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    create_user,
)
from query_refinement_module.db.models.audit_log import AuditLog
from query_refinement_module.db.models.feedback import Feedback


def _adapter(db, enforce_workflow_limit=False):
    return ChainlitRefinementAdapter(
        db,
        manager=SimpleNamespace(),
        session_manager=object(),
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=enforce_workflow_limit),
    )


@pytest.fixture
def user(test_db_session):
    return create_user(test_db_session, username="reviewer", password="s3cret-pass", email="r@example.org")


def test_authenticate_audits_success_and_failure(test_db_session, user):
    adapter = _adapter(test_db_session)

    assert adapter.authenticate("reviewer", "wrong") is None
    assert adapter.authenticate("reviewer", "s3cret-pass").id == user.id

    events = [log.event_type for log in test_db_session.query(AuditLog).order_by(AuditLog.id)]
    assert events == ["auth.login.failure", "auth.login.success"]
    assert all(log.details.get("client") == "chainlit" for log in test_db_session.query(AuditLog))


def test_list_frameworks_respects_access(monkeypatch, test_db_session, user):
    monkeypatch.setattr(adapter_module, "list_frameworks", lambda: ["pico_advanced", "cocopop", "legal_research"])
    assign_user_framework_access(test_db_session, user.id, "pico_advanced")
    adapter = _adapter(test_db_session)

    assert adapter.list_frameworks(user) == ["pico_advanced"]

    user.is_superuser = True
    assert adapter.list_frameworks(user) == ["cocopop", "legal_research", "pico_advanced"]


def test_find_resumable_query_ignores_synthesized(test_db_session, user):
    adapter = _adapter(test_db_session)
    done_session = create_query_session(test_db_session, user_id=user.id, framework_name="pico_advanced")
    done_query = create_query(test_db_session, session_id=done_session.id, original_query="finished question")
    done_query.refined_query = "Refined."
    open_session = create_query_session(test_db_session, user_id=user.id, framework_name="cocopop")
    open_query = create_query(test_db_session, session_id=open_session.id, original_query="open question")
    test_db_session.commit()

    resumable = adapter.find_resumable_query(user)

    assert resumable["query_id"] == open_query.id
    assert resumable["framework_name"] == "cocopop"


def test_build_trace_records_turns_and_enforces_ownership(test_db_session, user):
    adapter = _adapter(test_db_session)
    session = create_query_session(test_db_session, user_id=user.id, framework_name="pico_advanced")
    query = create_query(test_db_session, session_id=session.id, original_query="exercise for copd")
    step = create_refinement_step(test_db_session, query_id=query.id, aspect_name="Population", aspect_id="population")
    create_followup(test_db_session, refinement_step_id=step.id, question="Which adults?", answer="Adults over 40")

    trace = adapter.build_trace(user, query_id=query.id)

    assert trace[0]["aspect_id"] == "population"
    assert trace[0]["turns"][0]["question"] == "Which adults?"
    assert trace[0]["turns"][0]["answer"] == "Adults over 40"

    other = create_user(test_db_session, username="other", password="pass-1234")
    with pytest.raises(ResourceNotFoundError):
        adapter.build_trace(other, query_id=query.id)


def test_save_feedback_records_consent_and_workflow_completion(test_db_session, user):
    adapter = _adapter(test_db_session, enforce_workflow_limit=True)
    session = create_query_session(test_db_session, user_id=user.id, framework_name="pico_advanced")
    query = create_query(test_db_session, session_id=session.id, original_query="q")
    responses = SurveyResponses(framework_name="pico_advanced", query_id=query.id)
    responses.likert = {"overall_helpful": 4, "ease_of_use": 5}
    responses.free_text = {"most_helpful": "The examples", "improvements": None, "other": None}
    responses.consent = True

    feedback_id = adapter.save_feedback(
        user,
        query_id=query.id,
        rating=responses.rating,
        comments=responses.comments(),
        metadata=responses.to_metadata(),
        consent=True,
    )

    feedback = test_db_session.get(Feedback, feedback_id)
    assert feedback.rating == 4
    assert feedback.comments == "Most helpful: The examples"
    assert feedback.additional_metadata["pico_advanced_survey_v1"]["ease_of_use"] == 5
    assert feedback.additional_metadata["consent"] == {"selection": "yes"}
    assert query.consent_given is True
    assert user.has_completed_workflow is True
    assert adapter.workflow_limit_reached(user) is True


def test_survey_items_fall_back_to_generic_wording():
    assert "systematic review" in survey_items("pico_advanced")["overall_helpful"]
    assert survey_items("legal_research")["overall_helpful"] == survey_items(None)["overall_helpful"]


_SYNTHESIS = {
    "query_id": 3,
    "clarified_query": "In adults with COPD, does pulmonary rehabilitation improve exercise capacity?",
    "structured_output": {
        "dimensions_specifications": {"population": "Adults with COPD", "intervention": "Pulmonary rehabilitation"},
        "keyword_statement": "COPD pulmonary rehabilitation exercise capacity",
        "search_optimized": {
            "semantic": "Effect of pulmonary rehabilitation on exercise capacity in COPD",
            "keyword": {
                "structured": '("COPD" OR "chronic obstructive") AND ("pulmonary rehabilitation")',
                "combined_blocks": [{"role": "population_or_entity", "free_text": ["COPD", "chronic obstructive"], "controlled_vocabulary": {"MeSH": ["Pulmonary Disease, Chronic Obstructive"]}}],
            },
        },
        "search_filters": {"publication_years": "2015-2025", "publication_types": ["Randomized Controlled Trial"]},
    },
    "expansion_levels": [{"level": 0, "label": "Anchor", "boolean_query": "(COPD) AND (rehab)"}],
    "expansion_metadata": {"recommended_starting_level": 0},
}


def test_render_synthesis_markdown_includes_all_outputs():
    markdown = render_synthesis_markdown(_SYNTHESIS)

    assert "Adults with COPD" in markdown
    assert "Boolean search construction" in markdown
    assert "2015-2025" in markdown
    assert "Level 0: Anchor" in markdown
    assert "MeSH: Pulmonary Disease" in render_concept_blocks(_SYNTHESIS)


def test_markdown_export_includes_trace():
    export = {
        "query_id": 3,
        "framework": "pico_advanced",
        "exported_at": "2026-10-07T00:00:00+00:00",
        "original_query": "copd exercise",
        "synthesis": _SYNTHESIS,
        "refinement_trace": [
            {"aspect_name": "Population", "is_complete": True, "was_skipped": False, "final_value": "Adults with COPD",
             "turns": [{"question": "Which adults?", "answer": "Over 40"}]},
        ],
    }

    markdown = build_markdown_export(export)

    assert "### Population (complete)" in markdown
    assert "**Q:** Which adults?" in markdown
    assert "## Concept blocks" in markdown
    assert "## Search expansion levels" in markdown
    assert "### 1. Population / entity" in markdown


def test_format_prompt_numbers_examples_and_task_state_mapping():
    text = format_prompt({"name": "Population", "question": "Who?", "examples": ["Adults", "Children"]})
    assert "1. Adults" in text and "2. Children" in text

    assert task_state({"status": "active"}) == "RUNNING"
    assert task_state({"status": "completed"}) == "DONE"
    assert task_state({"status": "not started", "was_skipped": True}) == "DONE"
    assert task_state({"status": "not started"}) == "READY"


def test_survey_steps_cover_all_items_and_record_answers():
    from query_refinement_module.application.feedback_survey import apply_survey_answer, build_survey_steps

    steps = build_survey_steps("pico_advanced")
    responses = SurveyResponses(framework_name="pico_advanced", query_id=1)
    answers = {"choice": 3, "text": "  skip "}
    for step in steps:
        value = "yes" if step["key"] == "consent" else ("some" if step["key"] == "time_saved" else answers[step["kind"]])
        apply_survey_answer(responses, step, value)

    assert [s["key"] for s in steps][-1] == "consent"
    assert steps[-1]["skippable"] is False
    assert responses.rating == 3
    assert responses.time_saved == "some"
    assert responses.consent is True
    assert responses.free_text == {"most_helpful": None, "improvements": None, "other": None}
    assert responses.to_metadata()["pico_advanced_survey_v1"]["felt_in_control"] == 3


def test_render_search_validation_reports_repairs_and_status():
    from query_refinement_module.chainlit_app import render_search_validation

    synthesis = {"structured_output": {"search_quality": {
        "repairs": [{"action": "drop_block", "reason": "redundant", "role": "population_or_entity", "terms": ["COPD patients"]}],
        "final": {"search_ready": True, "block_count": 2, "aligned": True, "syntax_problems": [], "ungrounded_blocks": [], "leaked_terms": {}},
    }}}

    text = render_search_validation(synthesis)

    assert "Passed all checks" in text
    assert "Removed the *Population / entity* block" in text
    assert render_search_validation({"structured_output": {}}) is None
