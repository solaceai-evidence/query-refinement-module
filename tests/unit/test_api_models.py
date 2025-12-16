from query_refinement_module.api_models import (
    InteractionRequest,
    InteractionResponse,
    NextPrompt,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStatusResponse,
)
from query_refinement_module.schema import RefinementAspect


def make_aspect(aspect_id="aspect", name="Aspect"):
    return RefinementAspect(
        id=aspect_id,
        aspect_name=name,
        aspect_description=f"Description for {name}",
        refinement_instructions="Analyze {query}",
        depends_on=[],
    )


def test_next_prompt_dependency_context_defaults():
    prompt = NextPrompt(aspect_id="a", aspect_name="Aspect", question="Q")
    prompt.dependency_context["dep"] = "value"

    other = NextPrompt(aspect_id="b", aspect_name="Other", question="Q2")
    assert other.dependency_context == {}


def test_session_create_models_handle_defaults():
    req = SessionCreateRequest(original_query="query", refinement_framework=[make_aspect()])
    assert req.session_id is None
    assert req.metadata is None

    resp = SessionCreateResponse(session_id="id", summary={"total": 1}, next_prompt=None)
    resp.metadata["seen"] = True

    resp2 = SessionCreateResponse(session_id="id2", summary={}, next_prompt=None)
    assert resp2.metadata == {}


def test_interaction_models_defaults():
    req = InteractionRequest(session_id="s", message="hi")
    assert req.metadata is None

    resp = InteractionResponse(
        session_id="s",
        success=True,
        message="ok",
        next_prompt=None,
        summary={"total": 0},
    )
    resp.invalidated_aspects.append("a")
    resp.metadata["count"] = 1

    resp2 = InteractionResponse(
        session_id="s2",
        success=False,
        message="no",
        next_prompt=None,
        summary={},
    )
    assert resp2.invalidated_aspects == []
    assert resp2.metadata == {}
    assert resp2.session_complete is False


def test_session_status_response_defaults():
    status = SessionStatusResponse(
        session_id="s",
        summary={"total": 0},
        next_prompt=None,
        session_complete=False,
    )
    assert status.history is None
    status.metadata["k"] = "v"

    other = SessionStatusResponse(
        session_id="s2",
        summary={},
        next_prompt=None,
        session_complete=True,
    )
    assert other.metadata == {}