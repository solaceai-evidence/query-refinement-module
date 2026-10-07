from types import SimpleNamespace

import pytest

from query_refinement_module.api.session_manager import InMemorySessionManager


def test_inmemory_session_manager_save_and_load_roundtrip_without_redis():
    manager = InMemorySessionManager(session_ttl_seconds=60)

    # Minimal session-shaped object is enough for fallback serializer
    session = SimpleNamespace(
        original_query="test query",
        synthesis_requested=False,
        steps=[],
        _complete_framework=[],
    )

    saved = manager.save_session(123, session)
    assert saved is True

    loaded = manager.load_session(123, refinement_framework=[])
    assert loaded is not None
    assert loaded.original_query == "test query"
    assert loaded.synthesis_requested is False
    assert loaded.steps == []


@pytest.mark.asyncio
async def test_inmemory_session_manager_exposes_session_lock():
    manager = InMemorySessionManager(session_ttl_seconds=60)

    async with manager.session_lock(123):
        assert manager._get_session_lock(123).locked() is True

    assert manager._get_session_lock(123).locked() is False


def test_session_roundtrip_preserves_quick_replies():
    from query_refinement_module.schema.models import RefinementAspect
    from query_refinement_module.session_models import AspectRefinementState, RefinementSession

    aspect = RefinementAspect(id="population", name="Population", description="Who is studied")
    session = RefinementSession(original_query="exercise for copd")
    session._complete_framework = [aspect]
    session.steps.append(
        AspectRefinementState(
            refinement_aspect=aspect,
            follow_up_question="Which adults?",
            quick_replies=["Adults 40-65", "Adults 65+"],
        )
    )
    manager = InMemorySessionManager(session_ttl_seconds=60)

    manager.save_session(7, session)
    loaded = manager.load_session(7, refinement_framework=[aspect])

    assert loaded.steps[0].quick_replies == ["Adults 40-65", "Adults 65+"]
    assert loaded.steps[0].follow_up_question == "Which adults?"
