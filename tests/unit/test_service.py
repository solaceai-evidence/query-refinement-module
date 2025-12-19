import types
from typing import Any, Dict, List

import pytest

import query_refinement_module.service as service
from query_refinement_module.api_models import (
    InteractionRequest,
    SessionCreateRequest,
)
from query_refinement_module.schema import RefinementAspect


def make_aspect(aspect_id: str = "aspect") -> RefinementAspect:
    return RefinementAspect(
        id=aspect_id,
        aspect_name=f"Aspect {aspect_id}",
        aspect_description=f"Description {aspect_id}",
        refinement_instructions="Analyze {query}",
        depends_on=[],
    )


@pytest.fixture(autouse=True)
def immediate_to_thread(monkeypatch):
    async def _run(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(service.asyncio, "to_thread", _run)


def test_build_manager_from_env_uses_settings(monkeypatch):
    provider_kwargs = {"default_model": "m"}
    analyzer_kwargs = {"temperature": 0.2}

    class StubSettings:
        def as_provider_kwargs(self):
            return provider_kwargs

        def as_analyzer_kwargs(self):
            return analyzer_kwargs

    monkeypatch.setattr(service.LLMSettings, "from_env", classmethod(lambda cls: StubSettings()))

    created: Dict[str, Any] = {}

    class StubProvider:
        def __init__(self, **kwargs):
            created["provider"] = kwargs

    class StubAnalyzer:
        def __init__(self, provider, **kwargs):
            created["analyzer_provider"] = provider
            created["analyzer"] = kwargs

    monkeypatch.setattr(service, "LiteLLMProvider", StubProvider)
    monkeypatch.setattr(service, "LLMQueryAnalyzer", StubAnalyzer)

    manager = service.build_manager_from_env()

    assert created["provider"] == provider_kwargs
    assert created["analyzer"] == analyzer_kwargs
    assert created["analyzer_provider"] is manager.llm_provider
    assert manager.tracing_provider.__class__.__name__ == "NoOpTracingProvider"


def test_build_manager_from_env_accepts_explicit_settings(monkeypatch):
    class StubSettings:
        def __init__(self):
            self.called = []

        def as_provider_kwargs(self):
            self.called.append("provider")
            return {"default_model": "m"}

        def as_analyzer_kwargs(self):
            self.called.append("analyzer")
            return {"temperature": 0.3}

    monkeypatch.setattr(service, "LiteLLMProvider", lambda **_: "provider")
    monkeypatch.setattr(service, "LLMQueryAnalyzer", lambda provider, **__: (provider, {}))

    tracing = object()
    settings = StubSettings()
    manager = service.build_manager_from_env(settings=settings, tracing_provider=tracing)

    assert settings.called == ["provider", "analyzer"]
    assert manager.tracing_provider is tracing


class StubStorage:
    def __init__(self):
        self.saved: List[tuple] = []
        self.deleted: List[str] = []
        self.sessions: Dict[str, Any] = {}

    def save_session(self, session_id: str, session: Any) -> None:
        self.saved.append((session_id, session))
        self.sessions[session_id] = session

    def load_session(self, session_id: str) -> Any:
        return self.sessions[session_id]

    def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)
        self.sessions.pop(session_id, None)


class StubManager:
    def __init__(self, session):
        self.session = session
        self.summary = {"total_aspects": 1}
        self.initialize_calls: List[tuple] = []
        self.summary_calls = 0

    def initialize(self, query, framework):
        self.initialize_calls.append((query, framework))
        return self.session

    def get_initialization_summary(self, session):
        self.summary_calls += 1
        return self.summary

    def synthesize_refined_query(self, session):
        return {"refined_query": "refined", "used_llm": True}


@pytest.mark.asyncio
async def test_create_session(monkeypatch):
    session = object()
    manager = StubManager(session)
    storage = StubStorage()

    monkeypatch.setattr(
        service.QueryRefinementService,
        "_build_next_prompt",
        staticmethod(lambda _: "prompt"),
    )

    svc = service.QueryRefinementService(manager, storage, session_id_factory=lambda: "sid")
    req = SessionCreateRequest(original_query="query", refinement_framework=[make_aspect()], metadata={"source": "api"})

    resp = await svc.create_session(req)

    assert resp.session_id == "sid"
    assert resp.summary == manager.summary
    assert resp.next_prompt == "prompt"
    assert resp.metadata["session_id"] == "sid"
    assert resp.metadata["source"] == "api"
    assert storage.saved[-1][0] == "sid"
    assert manager.initialize_calls[0][0] == "query"
    assert isinstance(manager.initialize_calls[0][1][0], RefinementAspect)


class CommandSession:
    def __init__(self):
        self.command_calls: List[Any] = []
        self.synthesis_requested = False

    def handle_command(self, command_result):
        self.command_calls.append(command_result)
        return {"success": True, "message": "Handled", "invalidated": ["a"]}

    def get_active_step(self):
        return None

    def is_complete(self):
        return False

    def get_dependency_context(self, aspect_id):
        return {}


@pytest.mark.asyncio
async def test_submit_user_message_command(monkeypatch):
    session = CommandSession()
    manager = StubManager(session)
    storage = StubStorage()
    storage.sessions["sid"] = session

    monkeypatch.setattr(
        service.QueryRefinementService,
        "_build_next_prompt",
        staticmethod(lambda _: "prompt"),
    )

    svc = service.QueryRefinementService(manager, storage)
    req = InteractionRequest(session_id="sid", message="/skip")

    resp = await svc.submit_user_message(req)

    assert resp.success is True
    assert resp.message == "Handled"
    assert resp.invalidated_aspects == ["a"]
    assert storage.saved[-1][0] == "sid"
    assert session.command_calls


class ResponseStep:
    def __init__(self):
        self.analysis_suggested_question = "Ask?"
        self.refinement_question = "Ask?"  # Main question attribute
        self.refinement_aspect = types.SimpleNamespace(
            name="Aspect", 
            aspect_name="Aspect",
            id="aspect", 
            description="desc",
            aspect_description="desc",
            get_refinement_instructions_prompt=lambda *, statement: f"Analyze {statement}"
        )
        self.analysis_reason = "reason"
        self.follow_up_history: List[Dict[str, str]] = []
        self.is_complete = False
        self.needs_review = False

    def add_follow_up(self, question, response):
        self.follow_up_history.append({"question": question, "response": response})


class ResponseSession:
    def __init__(self, step: ResponseStep):
        self.step = step
        self.synthesis_requested = False
        self.original_query = "original"

    def get_active_step(self):
        if not self.step.is_complete:
            return self.step
        return None

    def get_dependency_context(self, aspect_id):
        return {}

    def is_complete(self):
        return self.step.is_complete

    def get_full_conversation(self):
        return "history"


@pytest.mark.asyncio
async def test_submit_user_message_records_response(monkeypatch):
    step = ResponseStep()
    session = ResponseSession(step)
    manager = StubManager(session)
    storage = StubStorage()
    storage.sessions["sid"] = session

    monkeypatch.setattr(
        service.QueryRefinementService,
        "_build_next_prompt",
        staticmethod(lambda _: "prompt"),
    )

    svc = service.QueryRefinementService(manager, storage)
    req = InteractionRequest(session_id="sid", message="Answer")

    resp = await svc.submit_user_message(req)

    assert resp.success is True
    assert step.is_complete is True
    assert step.follow_up_history[-1]["response"] == "Answer"
    assert resp.message.startswith("Recorded response")


@pytest.mark.asyncio
async def test_get_session_status(monkeypatch):
    session = ResponseSession(ResponseStep())
    session.step.is_complete = True
    manager = StubManager(session)
    storage = StubStorage()
    storage.sessions["sid"] = session

    monkeypatch.setattr(
        service.QueryRefinementService,
        "_build_next_prompt",
        staticmethod(lambda _: "prompt"),
    )

    svc = service.QueryRefinementService(manager, storage)
    status = await svc.get_session_status("sid")

    assert status.summary == manager.summary
    assert status.next_prompt == "prompt"
    assert status.history is not None


@pytest.mark.asyncio
async def test_delete_session():
    session = ResponseSession(ResponseStep())
    manager = StubManager(session)
    storage = StubStorage()
    storage.sessions["sid"] = session

    svc = service.QueryRefinementService(manager, storage)
    await svc.delete_session("sid")

    assert "sid" in storage.deleted
    assert "sid" not in storage.sessions


def test_build_next_prompt_returns_none_when_no_step():
    class EmptySession:
        def get_active_step(self):
            return None

    assert service.QueryRefinementService._build_next_prompt(EmptySession()) is None


def test_build_next_prompt_prefers_suggested_question():
    class Aspect:
        def __init__(self):
            self.id = "a"
            self.name = "Aspect"
            self.aspect_name = "Aspect"
            self.aspect_description = "desc"
            self.description = "desc"  # Legacy support

        def get_refinement_instructions_prompt(self, *, statement):
            return "Prompt"

    class Session:
        def __init__(self):
            self.original_query = "query"

        def get_active_step(self):
            step = types.SimpleNamespace(
                analysis_suggested_question="Ask",
                refinement_aspect=Aspect(),
                analysis_reason="why",
            )
            step.refinement_aspect = Aspect()
            step.analysis_suggested_question = "Ask"
            step.analysis_reason = "why"
            return step

        def get_dependency_context(self, aspect_id):
            return {"dep": {"value": "V"}}

    prompt = service.QueryRefinementService._build_next_prompt(Session())
    assert prompt.question == "Ask"
    assert prompt.dependency_context == {"dep": "V"}
    assert prompt.rationale == "why"


def test_build_next_prompt_uses_prompt_and_description():
    class Aspect:
        def __init__(self, raises=False):
            self.id = "a"
            self.name = "Aspect"
            self.aspect_name = "Aspect"
            self.aspect_description = "desc"
            self.description = "desc"  # Legacy support
            self.raises = raises

        def get_refinement_instructions_prompt(self, *, statement):
            if self.raises:
                raise RuntimeError("boom")
            return f"Prompt for {statement}"
        
        def get_refinement_instructions_prompt(self, *, statement):
            if self.raises:
                raise RuntimeError("boom")
            return f"Prompt for {statement}"

    class Session:
        def __init__(self):
            self.original_query = "query"
            self._first = True

        def get_active_step(self):
            if self._first:
                self._first = False
                aspect = Aspect()
            else:
                aspect = Aspect(raises=True)
            step = types.SimpleNamespace(
                analysis_suggested_question=None,
                refinement_aspect=aspect,
                analysis_reason=None,
            )
            return step

        def get_dependency_context(self, aspect_id):
            return {}

    session = Session()
    prompt = service.QueryRefinementService._build_next_prompt(session)
    assert prompt.question == "Prompt for query"

    prompt = service.QueryRefinementService._build_next_prompt(session)
    assert prompt.question == "desc"