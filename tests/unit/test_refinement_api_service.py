from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import query_refinement_module.application.refinement_api_service as service_module
from query_refinement_module.application.refinement_api_service import RefinementApiService
from query_refinement_module.api.exceptions import QueryRefinementException


class _SessionManager:
    def __init__(self, session=None):
        self._session = session

    def load_session(self, query_id, framework):
        return self._session

    @asynccontextmanager
    async def session_lock(self, query_id):
        yield

    def delete_session(self, query_id):
        return None

    def save_session(self, query_id, session):
        self._session = session


class _User:
    def __init__(self, user_id=1, is_superuser=False):
        self.id = user_id
        self.is_superuser = is_superuser
        self.has_completed_workflow = False


@pytest.mark.asyncio
async def test_normalize_workflow_returns_clarified_query(monkeypatch):
    user = _User()
    session = SimpleNamespace(synthesis_requested=True, is_complete=lambda: False)
    db_query = SimpleNamespace(
        id=7,
        original_query="copd rehabilitation",
        session=SimpleNamespace(user_id=user.id, framework_name="pico"),
    )

    manager = SimpleNamespace(
        _run_normalization=None,
    )

    async def _run_normalization(active_session):
        assert active_session is session
        return SimpleNamespace(
            clarified_query="Adults with COPD receiving pulmonary rehabilitation.",
            dimensions_specifications={"population": "Adults with COPD"},
        ), None

    manager._run_normalization = _run_normalization

    monkeypatch.setattr(service_module, "get_query", lambda db, query_id: db_query)
    monkeypatch.setattr(service_module, "get_framework", lambda framework_name: object())

    workflow_service = RefinementApiService(
        manager=manager,
        db=object(),
        session_manager=_SessionManager(session=session),
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )

    payload = await workflow_service.normalize_workflow(
        query_id=7,
        current_user=user,
        request_id="req-1",
    )

    assert payload == {
        "query_id": 7,
        "clarified_query": "Adults with COPD receiving pulmonary rehabilitation.",
        "dimensions_specifications": {"population": "Adults with COPD"},
        "used_llm": True,
    }


@pytest.mark.asyncio
async def test_normalize_workflow_rejects_incomplete_session(monkeypatch):
    user = _User()
    session = SimpleNamespace(synthesis_requested=False, is_complete=lambda: False)
    db_query = SimpleNamespace(
        id=8,
        original_query="copd rehabilitation",
        session=SimpleNamespace(user_id=user.id, framework_name="pico"),
    )

    monkeypatch.setattr(service_module, "get_query", lambda db, query_id: db_query)
    monkeypatch.setattr(service_module, "get_framework", lambda framework_name: object())

    workflow_service = RefinementApiService(
        manager=SimpleNamespace(),
        db=object(),
        session_manager=_SessionManager(session=session),
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )

    with pytest.raises(QueryRefinementException, match="not ready for normalization") as exc:
        await workflow_service.normalize_workflow(
            query_id=8,
            current_user=user,
            request_id="req-2",
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_represent_workflow_serializes_concept_graph():
    user = _User()

    class _ConceptNode:
        def model_dump(self):
            return {"query_role": "topic_or_condition", "domain_terms": ["pulmonary rehab"]}

    async def _run_semantic_representation(statement, model=None):
        assert statement == "Adults with COPD receiving pulmonary rehabilitation."
        assert model == "test-model"
        return SimpleNamespace(
            semantic_statement="semantic text",
            keyword_statement="keyword text",
            concept_graph={"copd": _ConceptNode()},
        ), None

    manager = SimpleNamespace(_run_semantic_representation=_run_semantic_representation)
    workflow_service = RefinementApiService(
        manager=manager,
        db=None,
        session_manager=None,
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )

    payload = await workflow_service.represent_workflow(
        statement="Adults with COPD receiving pulmonary rehabilitation.",
        model="test-model",
        current_user=user,
        request_id="req-3",
    )

    assert payload == {
        "semantic_statement": "semantic text",
        "keyword_statement": "keyword text",
        "concept_graph": {"copd": {"query_role": "topic_or_condition", "domain_terms": ["pulmonary rehab"]}},
        "used_llm": True,
    }


@pytest.mark.asyncio
async def test_expand_workflow_returns_expansion_payload():
    user = _User()

    class _Level:
        def __init__(self, level):
            self.level = level

        def model_dump(self, by_alias=False):
            return {"level": self.level, "label": f"Level {self.level}"}

    result = SimpleNamespace(
        levels=[_Level(0), _Level(1)],
        geography_broadening_strategy="none",
        recommended_starting_level=1,
        recommendation_rationale="start narrow",
        search_filters=SimpleNamespace(model_dump=lambda: {"publication_types": ["review"]}),
        phrases=["pulmonary rehabilitation"],
    )

    async def _generate_search_expansion_levels(search_input, model=None):
        assert search_input.clarified_query == "Adults with COPD receiving pulmonary rehabilitation."
        return result, {"status": "completed", "generated_level_count": 2}

    manager = SimpleNamespace(generate_search_expansion_levels=_generate_search_expansion_levels)
    workflow_service = RefinementApiService(
        manager=manager,
        db=None,
        session_manager=None,
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )

    payload = await workflow_service.expand_workflow(
        statement="Adults with COPD receiving pulmonary rehabilitation.",
        anchor_blocks=[],
        search_context=None,
        semantic_statement="semantic",
        keyword_statement="keyword",
        keyword_structured="structured",
        search_filters=None,
        phrases=None,
        model=None,
        current_user=user,
        request_id="req-4",
    )

    assert payload == {
        "levels": [{"level": 0, "label": "Level 0"}, {"level": 1, "label": "Level 1"}],
        "geography_broadening_strategy": "none",
        "recommended_starting_level": 1,
        "recommendation_rationale": "start narrow",
        "search_filters": {"publication_types": ["review"]},
        "phrases": ["pulmonary rehabilitation"],
        "metadata": {
            "status": "completed",
            "generated_level_count": 2,
            "geography_broadening_strategy": "none",
            "recommended_starting_level": 1,
            "recommendation_rationale": "start narrow",
            "search_filters": {"publication_types": ["review"]},
            "phrases": ["pulmonary rehabilitation"],
        },
    }
