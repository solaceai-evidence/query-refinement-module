import logging
from types import SimpleNamespace
from typing import List, Optional

import query_refinement_module.cli as cli
from query_refinement_module.providers import FileTracingProvider, NoOpTracingProvider


class StubSettings:
    def __init__(self, provider_kwargs=None, analyzer_kwargs=None):
        self._provider_kwargs = provider_kwargs or {"default_model": "demo"}
        self._analyzer_kwargs = analyzer_kwargs or {"temperature": 0.1}
        self.terminal_reinforcement_threshold = 3  # Default value

    def as_provider_kwargs(self):
        return self._provider_kwargs

    def as_analyzer_kwargs(self):
        return self._analyzer_kwargs


def test_build_manager_constructs_components(monkeypatch):
    """Test build_manager creates provider and manager with correct settings."""
    created = {}

    monkeypatch.setattr(cli.LLMSettings, "from_env", classmethod(lambda cls: StubSettings()))

    class FakeProvider:
        def __init__(self, **kwargs):
            created["provider_kwargs"] = kwargs

    monkeypatch.setattr(cli, "LiteLLMProvider", FakeProvider)
    monkeypatch.setattr(cli, "ConsoleTracing", lambda: "tracer")

    manager = cli.build_manager(enable_tracing=True)

    assert created["provider_kwargs"] == {"default_model": "demo"}
    assert isinstance(manager.llm_provider, FakeProvider)
    assert manager.tracing_provider == "tracer"


def test_build_manager_without_tracing(monkeypatch):
    monkeypatch.setattr(cli.LLMSettings, "from_env", classmethod(lambda cls: StubSettings()))
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda **_: "provider")

    manager = cli.build_manager(enable_tracing=False)

    assert manager.tracing_provider.__class__ is NoOpTracingProvider


def test_build_manager_with_trace_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.LLMSettings, "from_env", classmethod(lambda cls: StubSettings()))

    class DummyProvider:
        pass

    monkeypatch.setattr(cli, "LiteLLMProvider", lambda **_: DummyProvider())

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    try:
        manager = cli.build_manager(enable_tracing=False, trace_dir=str(tmp_path / "trace"))
        assert isinstance(manager.tracing_provider, FileTracingProvider)
        log_file = tmp_path / "trace" / "application.log"
        assert log_file.exists()
    finally:
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                handler.close()
                root_logger.removeHandler(handler)
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)


def test_format_dependency_context_formats(monkeypatch):
    class StubSession:
        def get_dependency_context(self, aspect_id):
            return {
                "dep": {"name": "Dependency", "value": "Answer"},
                "missing": {},
            }

    session = StubSession()
    formatted = cli._format_dependency_context(session, "aspect")
    assert formatted.startswith("Dependency Context:")
    assert "• Dependency: Answer" in formatted


def test_print_summary_outputs(capsys):
    class StubManager:
        def get_initialization_summary(self, session):
            return {
                "total_aspects": 2,
                "incomplete_count": 1,
                "complete_count": 1,
                "aspects": [
                    {"is_complete": False, "name": "A", "reasoning": "Missing"},
                    {"is_complete": True, "name": "B"},
                ],
            }

    cli._print_summary(StubManager(), object())
    out = capsys.readouterr().out
    assert "SESSION SUMMARY" in out
    assert "[NEEDS_REFINEMENT] A" in out
    assert "→ Missing" in out


def test_run_cli_handles_missing_framework(monkeypatch, capsys):
    import asyncio
    manager = SimpleNamespace()
    monkeypatch.setattr(cli.registry, "get_framework", lambda name: (_ for _ in ()).throw(ValueError("missing")))

    asyncio.run(cli.run_cli(manager, "demo", "query"))
    out = capsys.readouterr().out
    assert "Error: missing" in out


class StubStep:
    def __init__(self, name="Aspect", question: Optional[str] = None):
        self.refinement_aspect = SimpleNamespace(
            name=name,
            id="aspect",
            description="Test aspect description"
        )
        self.analysis_suggested_question = question
        self.refinement_question = question
        self.needs_review = False
        self.follow_up_history: List[dict] = []
        self.is_complete = False

    def add_follow_up(self, question, response):
        self.follow_up_history.append({"question": question, "response": response})


class StubSession:
    def __init__(self, step: StubStep, dependency_context=None):
        self._step = step
        self._dependency_context = dependency_context or {}
        self.synthesis_requested = False
        self.command_calls: List[dict] = []
        self.original_query = "query"
        self.steps = [step] if step else []

    def get_active_step(self):
        if self._step and not self._step.is_complete:
            return self._step
        return None
    
    def get_next_unrefined_aspect(self):
        """Get next step that needs refinement."""
        return self.get_active_step()

    def get_dependency_context(self, aspect_id):
        return self._dependency_context

    def handle_command(self, command_result):
        self.command_calls.append(command_result)
        self.synthesis_requested = True
        return {"message": "Handled", "submit": True}

    def get_full_conversation(self):
        return "conversation"


class StubManager:
    def __init__(self, session: StubSession):
        self.session = session
        self.summary_calls = 0
        self.parallel_config = None  # Add parallel_config attribute

    def initialize(self, query, framework):
        return self.session
    
    def initialize_sequential(self, query, framework):
        return self.session

    def get_initialization_summary(self, session):
        self.summary_calls += 1
        return {
            "total_aspects": 1,
            "incomplete_count": 1,
            "complete_count": 0,
            "aspects": [{"is_complete": False, "name": "Aspect"}],
        }

    async def get_analysis_prompts(self, session, aspect_id, mode='initial'):
        """Stub for unified prompt generation"""
        from query_refinement_module.schema.response import DimensionEvaluationResponse
        return DimensionEvaluationResponse(
            complete=False,
            question="test question?",
            current=""
        )
    
    def process_analysis_result(self, session, aspect_id, result):
        """Stub for processing analysis result"""
        return {
            "complete": False,
            "needs_followup": True
        }

    async def run_followup_until_clear(self, session, aspect_id=None, max_rounds=5):
        """Stub for follow-up loop"""
        return {
            "is_complete": True,
            "rounds": 1,
            "status": "complete"
        }

    async def synthesize_refined_query(self, session):
        return {"integrated_statement": "refined", "used_llm": True}


def test_run_cli_processes_answer(monkeypatch, capsys):
    import asyncio
    step = StubStep(question="Ask?")
    session = StubSession(step)
    manager = StubManager(session)

    inputs = iter(["answer"])
    monkeypatch.setattr(cli.registry, "get_framework", lambda name: [])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    asyncio.run(cli.run_cli(manager, "demo", "query"))

    out = capsys.readouterr().out
    # Check for actual output (analysis completion and synthesis)
    assert "Analyzing your answer" in out or "test question?" in out
    assert "Original:" in out
    assert "Refined:" in out
    assert step.follow_up_history[0]["response"] == "answer"


def test_run_cli_handles_command(monkeypatch, capsys):
    import asyncio
    step = StubStep()
    session = StubSession(step)
    manager = StubManager(session)

    inputs = iter(["/submit"])
    monkeypatch.setattr(cli.registry, "get_framework", lambda name: [])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    asyncio.run(cli.run_cli(manager, "demo", "query"))

    out = capsys.readouterr().out
    assert "Handled" in out
    # Check for synthesis section instead of "RESULTS"
    assert "GENERATING REFINED QUERY" in out or "Original:" in out
    assert session.command_calls


def test_parse_args_defaults():
    args = cli.parse_args([])
    assert args.framework is None
    assert args.query is None
    assert args.list_frameworks is False
    assert args.trace is False
    assert args.trace_dir is None
    assert args.log_dir is None


def test_parse_args_with_values():
    args = cli.parse_args([
        "--framework",
        "demo",
        "--query",
        "text",
        "--list-frameworks",
        "--trace",
        "--trace-dir",
        "traces",
        "--log-dir",
        "logs",
    ])
    assert args.framework == "demo"
    assert args.query == "text"
    assert args.trace_dir == "traces"
    assert args.log_dir == "logs"
    assert args.list_frameworks is True
    assert args.trace is True


def test_main_handles_reload_error(monkeypatch, capsys):
    def raise_error(*_, **__):
        raise cli.registry.FrameworkLoadError("bad")

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda argv=None: SimpleNamespace(
            list_frameworks=False,
            framework=None,
            query=None,
            trace=False,
            trace_dir=None,
            log_dir=None,
        ),
    )
    monkeypatch.setattr(cli.registry, "reload_from_env", raise_error)
    monkeypatch.setattr(cli.registry, "get_last_load_error", lambda: "extra")

    cli.main([])
    out = capsys.readouterr().out
    assert "Failed to load refinement frameworks" in out
    assert "extra" in out


def test_main_lists_frameworks(monkeypatch, capsys):
    args = SimpleNamespace(
        list_frameworks=True,
        framework=None,
        query=None,
        trace=False,
        trace_dir=None,
        log_dir=None,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A", "B"])

    cli.main([])
    out = capsys.readouterr().out
    assert "Available frameworks" in out
    assert "- A" in out


def test_main_requires_framework_selection(monkeypatch, capsys):
    args = SimpleNamespace(
        list_frameworks=False,
        framework=None,
        query="query",
        trace=False,
        trace_dir=None,
        log_dir=None,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A", "B"])

    cli.main([])
    out = capsys.readouterr().out
    assert "Select a framework" in out


def test_main_validates_framework_name(monkeypatch, capsys):
    args = SimpleNamespace(
        list_frameworks=False,
        framework="C",
        query="query",
        trace=False,
        trace_dir=None,
        log_dir=None,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A", "B"])

    cli.main([])
    out = capsys.readouterr().out
    assert "Framework 'C' not found" in out


def test_main_prompts_for_query(monkeypatch, capsys):
    args = SimpleNamespace(
        list_frameworks=False,
        framework="A",
        query=None,
        trace=False,
        trace_dir=None,
        log_dir=None,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    cli.main([])
    out = capsys.readouterr().out
    assert "A non-empty query" in out


def test_main_handles_build_manager_error(monkeypatch, capsys):
    args = SimpleNamespace(
        list_frameworks=False,
        framework="A",
        query="query",
        trace=False,
        trace_dir=None,
        log_dir=None,
        no_parallel=False,
        parallel=False,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A"])
    monkeypatch.setattr(
        cli,
        "build_manager",
        lambda enable_tracing=False, trace_dir=None, log_dir=None, parallel_enabled=True: (_ for _ in ()).throw(RuntimeError("fail")),
    )

    cli.main([])
    out = capsys.readouterr().out
    assert "Failed to initialise LLM provider" in out


def test_main_invokes_run_cli(monkeypatch):
    args = SimpleNamespace(
        list_frameworks=False,
        framework="A",
        query="query",
        trace=True,
        trace_dir=None,
        log_dir=None,
        no_parallel=False,
        parallel=False,
    )
    monkeypatch.setattr(cli, "parse_args", lambda argv=None: args)
    monkeypatch.setattr(cli.registry, "reload_from_env", lambda **_: {})
    monkeypatch.setattr(cli.registry, "list_frameworks", lambda: ["A"])

    called = {}
    monkeypatch.setattr(
        cli,
        "build_manager",
        lambda enable_tracing, trace_dir=None, log_dir=None, parallel_enabled=True: "manager",
    )
    async def fake_run_cli(manager, framework, query, parallel_enabled=True):
        called.update({"manager": manager, "framework": framework, "query": query})
    monkeypatch.setattr(cli, "run_cli", fake_run_cli)

    cli.main([])
    assert called == {"manager": "manager", "framework": "A", "query": "query"}