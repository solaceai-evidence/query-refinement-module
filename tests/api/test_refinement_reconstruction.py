import contextlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import query_refinement_module.schema.registry as registry
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.api.main import app
from query_refinement_module.db.crud import (
    assign_user_framework_access,
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    create_user,
    get_query,
    get_query_refinement_steps,
    get_refinement_step_by_aspect,
    get_step_followups,
    update_refinement_step_generated_question,
)
from query_refinement_module.db.session import get_db
from query_refinement_module.schema.models import RefinementAspect


FRAMEWORK_NAME = "test_reconstruction"


@pytest.fixture
def db(test_db_session):
    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield test_db_session
    app.dependency_overrides.clear()


@pytest.fixture
def registered_framework():
    framework = [
        RefinementAspect(
            id="population",
            name="Population",
            description="Target population characteristics",
        )
    ]
    original_frameworks = registry._FRAMEWORKS.copy()
    registry._FRAMEWORKS[FRAMEWORK_NAME] = framework
    try:
        yield framework
    finally:
        registry._FRAMEWORKS = original_frameworks


class _CacheMissSessionManager:
    def __init__(self):
        self.saved_sessions = {}
        self.load_calls = 0

    @contextlib.asynccontextmanager
    async def session_lock(self, query_id: int):
        yield

    def load_session(self, query_id: int, framework, request_id=None):
        self.load_calls += 1
        return None

    def save_session(self, query_id: int, session, request_id=None):
        self.saved_sessions[query_id] = session
        return True

    def delete_session(self, query_id: int):
        self.saved_sessions.pop(query_id, None)
        return True


class _StubManager:
    def __init__(self):
        self.initialize_calls = []
        self.followup_calls = []

    def initialize_sequential(self, original_query, framework):
        from query_refinement_module.core import RefinementSession

        session = RefinementSession(original_query=original_query)
        session._complete_framework = list(framework)
        for aspect in framework:
            session.add_step(aspect)
        self.initialize_calls.append(original_query)
        return session

    async def get_analysis_prompts(self, *, session, aspect_id, mode):
        active_step = session.get_active_step()
        self.followup_calls.append(
            {
                "aspect_id": aspect_id,
                "mode": mode,
                "active_step_id": active_step.refinement_aspect.id if active_step else None,
                "history_len": len(active_step.conversation_history) if active_step else 0,
            }
        )
        assert active_step is not None
        assert active_step.refinement_aspect.id == "population"
        return SimpleNamespace(
            complete=False,
            current="Adults with COPD aged 40-65",
            question="Any specific comorbidities?",
        )

    def process_analysis_result(self, session, aspect_id, result):
        step = session.get_step_by_aspect_id(aspect_id)
        assert step is not None
        step.normalized_value = result.current
        step.follow_up_question = result.question
        step.is_complete = bool(result.complete)
        return {
            "complete": result.complete,
            "aspect_id": aspect_id,
            "next_question": result.question,
        }

    def get_initialization_summary(self, session):
        aspects = []
        completed = 0
        for step in session.steps:
            if step.is_complete:
                completed += 1
            aspects.append(
                {
                    "aspect_id": step.refinement_aspect.id,
                    "name": step.refinement_aspect.name,
                    "is_complete": step.is_complete,
                    "status": "completed" if step.is_complete else "active",
                }
            )
        return {
            "total_aspects": len(session.steps),
            "completed_aspects": completed,
            "aspects": aspects,
        }


class _GuardedStatusManager(_StubManager):
    async def get_analysis_prompts(self, *, session, aspect_id, mode):
        raise AssertionError("status should not trigger prompt generation")


class _LockTrackingSessionManager(_CacheMissSessionManager):
    def __init__(self, session=None):
        super().__init__()
        self.locked_query_ids = []
        self.session = session
        self.deleted_sessions = []

    @contextlib.asynccontextmanager
    async def session_lock(self, query_id: int):
        self.locked_query_ids.append(query_id)
        yield

    def load_session(self, query_id: int, framework, request_id=None):
        self.load_calls += 1
        return self.session

    def delete_session(self, query_id: int):
        self.deleted_sessions.append(query_id)
        return True


class _SynthesisManager:
    async def synthesize_refined_query(self, session):
        return {
            "integrated_statement": "Adults with COPD receiving pulmonary rehabilitation.",
            "dimensions_specifications": {"population": "Adults with COPD"},
            "search_optimized": {"semantic": "pulmonary rehabilitation COPD adults"},
            "search_filters": {"publication_types": ["Systematic review"]},
            "terminology": {"synonyms": {"COPD": ["chronic obstructive pulmonary disease"]}},
            "used_llm": True,
        }


class _SkipRefinementManager(_StubManager):
    def __init__(self):
        super().__init__()
        self.synthesis_sessions = []

    async def synthesize_refined_query(self, session):
        self.synthesis_sessions.append(session)
        assert session.synthesis_requested is True
        assert all(step.is_complete and step.was_skipped for step in session.steps)
        return {
            "integrated_statement": "Adults with COPD receiving pulmonary rehabilitation.",
            "dimensions_specifications": {"population": "Adults with COPD"},
            "search_optimized": {"semantic": "pulmonary rehabilitation COPD adults"},
            "search_filters": {"publication_types": ["Systematic review"]},
            "terminology": {"synonyms": {"COPD": ["chronic obstructive pulmonary disease"]}},
            "metadata": {"total_tokens": 321},
            "used_llm": True,
        }


@pytest.fixture
def auth_user_and_token(db: Session):
    user = create_user(
        db,
        username="reconstruct_user",
        email="reconstruct@test.com",
        password="Reconstruct123!",
        name="Reconstruction User",
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "reconstruct@test.com", "password": "Reconstruct123!"},
    )
    assert response.status_code == 200
    return user, client


def test_submit_answer_reconstructs_unfinished_step_after_cache_miss(db: Session, auth_user_and_token, registered_framework):
    user, client = auth_user_and_token
    framework = registered_framework
    stub_manager = _StubManager()
    stub_session_manager = _CacheMissSessionManager()

    app.dependency_overrides[get_refinement_manager] = lambda: stub_manager
    app.dependency_overrides[get_session_manager] = lambda: stub_session_manager

    db_session = create_query_session(db, user_id=user.id, framework_name=FRAMEWORK_NAME)
    db_query = create_query(db, session_id=db_session.id, original_query="COPD therapy question")

    population_step = create_refinement_step(
        db,
        query_id=db_query.id,
        aspect_name="Population",
        aspect_id="population",
    )
    create_followup(
        db,
        refinement_step_id=population_step.id,
        question="Who is the target population?",
        answer="Adults with COPD",
    )
    update_refinement_step_generated_question(
        db,
        population_step.id,
        "Can you narrow that to a specific age group?",
    )

    response = client.post(
        f"/api/v1/refinement/queries/{db_query.id}/answer",
        json={"answer": "Adults aged 40-65"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_complete"] is False
    assert payload["next_prompt"]["aspect_id"] == "population"
    assert payload["next_prompt"]["question"] == "Any specific comorbidities?"

    assert stub_session_manager.load_calls == 1
    reconstructed = stub_session_manager.saved_sessions[db_query.id]
    active_step = reconstructed.get_active_step()
    assert active_step is not None
    assert active_step.refinement_aspect.id == "population"
    assert len(active_step.conversation_history) == 2
    assert active_step.conversation_history[-1]["response"] == "Adults aged 40-65"
    assert active_step.follow_up_question == "Any specific comorbidities?"

    db_step = get_refinement_step_by_aspect(db, query_id=db_query.id, aspect_id="population")
    assert db_step is not None
    followups = get_step_followups(db, refinement_step_id=db_step.id)
    assert len(followups) == 2
    assert followups[-1].answer == "Adults aged 40-65"

    assert stub_manager.followup_calls == [
        {
            "aspect_id": "population",
            "mode": "followup",
            "active_step_id": "population",
            "history_len": 2,
        }
    ]


def test_status_is_read_only_on_cache_miss(db: Session, auth_user_and_token, registered_framework):
    user, client = auth_user_and_token
    stub_manager = _GuardedStatusManager()
    stub_session_manager = _CacheMissSessionManager()

    app.dependency_overrides[get_refinement_manager] = lambda: stub_manager
    app.dependency_overrides[get_session_manager] = lambda: stub_session_manager

    try:
        db_session = create_query_session(db, user_id=user.id, framework_name=FRAMEWORK_NAME)
        db_query = create_query(db, session_id=db_session.id, original_query="COPD therapy question")

        create_refinement_step(
            db,
            query_id=db_query.id,
            aspect_name="Population",
            aspect_id="population",
        )

        response = client.get(f"/api/v1/refinement/queries/{db_query.id}/status")

        assert response.status_code == 200
        payload = response.json()
        assert payload["query_id"] == db_query.id
        assert payload["current_aspect"] == "Population"
        assert payload["next_prompt"] is None
        assert payload["ready_for_synthesis"] is False
        assert stub_session_manager.load_calls == 1
        assert stub_session_manager.saved_sessions == {}
        assert stub_manager.followup_calls == []
    finally:
        app.dependency_overrides.pop(get_refinement_manager, None)
        app.dependency_overrides.pop(get_session_manager, None)


def test_resume_generates_prompt_after_cache_miss(db: Session, auth_user_and_token, registered_framework):
    user, client = auth_user_and_token
    stub_manager = _StubManager()
    stub_session_manager = _CacheMissSessionManager()

    app.dependency_overrides[get_refinement_manager] = lambda: stub_manager
    app.dependency_overrides[get_session_manager] = lambda: stub_session_manager

    try:
        db_session = create_query_session(db, user_id=user.id, framework_name=FRAMEWORK_NAME)
        db_query = create_query(db, session_id=db_session.id, original_query="COPD therapy question")

        population_step = create_refinement_step(
            db,
            query_id=db_query.id,
            aspect_name="Population",
            aspect_id="population",
        )

        response = client.post(f"/api/v1/refinement/queries/{db_query.id}/resume")

        assert response.status_code == 200
        payload = response.json()
        assert payload["current_aspect"] == "Population"
        assert payload["next_prompt"]["aspect_id"] == "population"
        assert payload["next_prompt"]["question"] == "Any specific comorbidities?"
        assert stub_session_manager.load_calls == 1
        assert db_query.id in stub_session_manager.saved_sessions

        db_step = get_refinement_step_by_aspect(db, query_id=db_query.id, aspect_id="population")
        assert db_step is not None
        assert db_step.id == population_step.id
        assert db_step.generated_question == "Any specific comorbidities?"
    finally:
        app.dependency_overrides.pop(get_refinement_manager, None)
        app.dependency_overrides.pop(get_session_manager, None)


def test_synthesize_route_acquires_session_lock(db: Session, auth_user_and_token, registered_framework, monkeypatch):
    user, client = auth_user_and_token
    stub_manager = _StubManager()
    session = stub_manager.initialize_sequential("COPD therapy question", registered_framework)
    session.synthesis_requested = True
    session_manager = _LockTrackingSessionManager(session=session)

    app.dependency_overrides[get_refinement_manager] = lambda: _SynthesisManager()
    app.dependency_overrides[get_session_manager] = lambda: session_manager

    async def _track_progress(**kwargs):
        return None

    class _Tracker:
        async def create(self, **kwargs):
            return None

        async def increment_llm_calls(self, query_id: str):
            return None

    monkeypatch.setattr("query_refinement_module.api.routes.refinement.track_progress", _track_progress)
    monkeypatch.setattr("query_refinement_module.api.routes.refinement.get_progress_tracker", lambda: _Tracker())
    monkeypatch.setattr(
        "query_refinement_module.api.routes.refinement.get_settings",
        lambda: SimpleNamespace(enforce_workflow_limit=False),
    )
    monkeypatch.setattr(
        "query_refinement_module.services.webhook_service.dispatch_webhook_event_async",
        lambda *args, **kwargs: None,
    )

    try:
        db_session = create_query_session(db, user_id=user.id, framework_name=FRAMEWORK_NAME)
        db_query = create_query(db, session_id=db_session.id, original_query="COPD therapy question")

        response = client.post(
            "/api/v1/refinement/synthesize",
            json={"query_id": db_query.id},
        )

        assert response.status_code == 200
        assert session_manager.locked_query_ids == [db_query.id]
        assert session_manager.deleted_sessions == [db_query.id]
    finally:
        app.dependency_overrides.pop(get_refinement_manager, None)
        app.dependency_overrides.pop(get_session_manager, None)


def test_start_skip_refinement_returns_embedded_synthesis_and_skips_steps(
    db: Session,
    auth_user_and_token,
    registered_framework,
    monkeypatch,
):
    user, client = auth_user_and_token
    manager = _SkipRefinementManager()
    session_manager = _LockTrackingSessionManager()
    assign_user_framework_access(db, user.id, FRAMEWORK_NAME)

    app.dependency_overrides[get_refinement_manager] = lambda: manager
    app.dependency_overrides[get_session_manager] = lambda: session_manager

    async def _track_progress(**kwargs):
        return None

    class _Tracker:
        async def create(self, **kwargs):
            return None

        async def increment_llm_calls(self, query_id: str):
            return None

    monkeypatch.setattr("query_refinement_module.api.routes.refinement.track_progress", _track_progress)
    monkeypatch.setattr("query_refinement_module.api.routes.refinement.get_progress_tracker", lambda: _Tracker())
    monkeypatch.setattr(
        "query_refinement_module.api.routes.refinement.get_settings",
        lambda: SimpleNamespace(enforce_workflow_limit=False),
    )
    monkeypatch.setattr(
        "query_refinement_module.services.webhook_service.dispatch_webhook_event_async",
        lambda *args, **kwargs: None,
    )

    try:
        response = client.post(
            "/api/v1/refinement/start",
            json={
                "original_query": "effects of pulmonary rehabilitation in COPD",
                "framework_name": FRAMEWORK_NAME,
                "source": "api_integration",
                "skip_refinement": True,
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["ready_for_synthesis"] is True
        assert payload["next_prompt"] is None
        assert payload["summary"]["aspects_needing_refinement"] == 0
        assert payload["synthesis"]["integrated_statement"] == (
            "Adults with COPD receiving pulmonary rehabilitation."
        )
        assert payload["synthesis"]["structured_output"]["dimensions_specifications"] == {
            "population": "Adults with COPD"
        }

        assert len(manager.synthesis_sessions) == 1
        assert payload["query_id"] in session_manager.saved_sessions
        assert session_manager.deleted_sessions == [payload["query_id"]]

        db_query = get_query(db, payload["query_id"])
        assert db_query is not None
        assert db_query.integrated_statement == "Adults with COPD receiving pulmonary rehabilitation."
        assert db_query.synthesis_metadata == {"total_tokens": 321}

        db_steps = get_query_refinement_steps(db, payload["query_id"])
        assert len(db_steps) == 1
        assert all(step.was_skipped for step in db_steps)
    finally:
        app.dependency_overrides.pop(get_refinement_manager, None)
        app.dependency_overrides.pop(get_session_manager, None)