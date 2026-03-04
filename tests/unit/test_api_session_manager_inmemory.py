from types import SimpleNamespace

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
