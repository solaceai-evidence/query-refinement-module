import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import pytest

from query_refinement_module.core import (
    COMMAND_ALIASES,
    CommandResult,
    QueryAspectRefiner,
    QueryRefinementManager,
    QueryRefinementSession,
    UserCommand,
    get_help_text,
    is_user_command,
    parse_user_command,
)
from query_refinement_module.interfaces import (
    AspectAnalysisResult,
    LLMCompletionResult,
    LLMProviderInterface,
    QueryAnalyzerInterface,
    TracingProviderInterface,
)
from query_refinement_module.schema import RefinementAspect


# ---------------------------------------------------------------------------
# Helper factories and doubles
# ---------------------------------------------------------------------------

def make_aspect(
    *,
    aspect_id: str = "demo",
    name: str = "Demo Aspect",
    description: str = "Demo description",
    analysis_prompt: str = "Analyze {query}",
    system_prompt: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
    examples: Optional[Dict[str, Any]] = None,
    depends_on: Optional[List[str]] = None,
    allow_follow_up: bool = False,
    max_follow_ups: int = 3,
) -> RefinementAspect:
    return RefinementAspect(
        id=aspect_id,
        name=name,
        description=description,
        analysis_prompt=analysis_prompt,
        system_prompt=system_prompt,
        response_format=response_format,
        examples=examples,
        depends_on=depends_on or [],
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )


class DummyCompletionResult(LLMCompletionResult):
    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"DummyCompletionResult(context={self.context!r})"


class StubLLMProvider(LLMProviderInterface):
    def __init__(self, responses: Iterable[Any]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def complete(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "kwargs": kwargs,
            }
        )
        if not self._responses:
            raise RuntimeError("No more stubbed responses available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMCompletionResult):
            return item
        return DummyCompletionResult(context=item, model="dummy")

    def get_model_info(self, model: str) -> Dict[str, Any]:  # pragma: no cover - unused
        return {}


class StubQueryAnalyzer(QueryAnalyzerInterface):
    def __init__(self, results: Dict[str, Any]):
        self.results = results
        self.calls: List[Dict[str, Any]] = []

    def analyze_aspect(
        self,
        query: str,
        aspect: RefinementAspect,
        dependency_context: Optional[Dict[str, str]] = None,
        llm_provider: Optional[LLMProviderInterface] = None,
    ) -> AspectAnalysisResult:
        self.calls.append(
            {
                "query": query,
                "aspect_id": aspect.id,
                "dependency_context": dependency_context,
            }
        )
        result = self.results[aspect.id]
        if callable(result):
            return result(dependency_context or {})
        return result


@dataclass
class _TraceContext:
    name: str
    metadata: Optional[Dict[str, Any]] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - nothing to clean up
        return False

    def add_attribute(self, key: str, value: Any):
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value


class StubTracingProvider(TracingProviderInterface):
    def __init__(self):
        self.operations: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []

    def trace_operation(
        self,
        name: str,
        operation_type: str = "function",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        ctx = _TraceContext(name=name, metadata=metadata)
        self.operations.append({"name": name, "operation_type": operation_type, "metadata": metadata})
        return ctx

    def log_event(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.events.append({"event": event_name, "level": level, "metadata": metadata})

    def is_enabled(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# is_user_command / parse_user_command / get_help_text
# ---------------------------------------------------------------------------

def test_is_user_command_recognizes_prefix():
    assert is_user_command("/skip")
    assert not is_user_command("skip")
    assert not is_user_command("")


def test_parse_user_command_handles_alias_and_arguments():
    result = parse_user_command("/prev")
    assert result.command is UserCommand.PREVIOUS
    assert result.is_valid

    goto = parse_user_command("/goto 3")
    assert goto.command is UserCommand.GOTO
    assert goto.argument == "3"


def test_parse_user_command_validates_missing_argument():
    result = parse_user_command("/goto")
    assert not result.is_valid
    assert result.error_message.startswith("/goto requires")


def test_parse_user_command_rejects_unknown_command():
    result = parse_user_command("/unknown")
    assert not result.is_valid
    assert result.error_message == "Unknown command: /unknown. Type /help for available commands."


def test_get_help_text_lists_commands():
    help_text = get_help_text()
    for command in set(COMMAND_ALIASES.values()):
        aliases = [alias for alias, mapped in COMMAND_ALIASES.items() if mapped is command]
        assert any(f"/{alias}" in help_text for alias in aliases)


# ---------------------------------------------------------------------------
# QueryAspectRefiner behaviour
# ---------------------------------------------------------------------------

def test_query_aspect_refiner_follow_up_tracking():
    aspect = make_aspect()
    refiner = QueryAspectRefiner(refinement_aspect=aspect)

    assert refiner.follow_up_count == 0
    assert refiner.final_response is None

    refiner.add_follow_up(question="Q1", response="Answer")
    assert refiner.follow_up_count == 1
    assert refiner.final_response == "Answer"


def test_query_aspect_refiner_get_prompts_includes_dependency_context(caplog):
    dep_aspect = make_aspect(aspect_id="dep", name="Dep", description="dep desc")
    target_aspect = make_aspect(
        aspect_id="target",
        name="Target",
        description="Target desc",
        depends_on=["dep", "missing"],
    )

    dep_refiner = QueryAspectRefiner(refinement_aspect=dep_aspect)
    dep_refiner.add_follow_up("Q", "Value")

    target_refiner = QueryAspectRefiner(refinement_aspect=target_aspect)

    context = {
        "dep": {"name": "Dep", "value": "Value"},
    }

    with caplog.at_level("WARNING"):
        system_prompt, user_prompt = target_refiner.get_prompts(
            query="Original query",
            dependency_context=context,
        )

    assert system_prompt.startswith("You refine research queries")
    assert "Previous refinements" in user_prompt
    assert "Dep: Value" in user_prompt
    assert "Original query" in user_prompt
    assert any("depends on ['missing']" in record.message for record in caplog.records)


def test_query_aspect_refiner_follow_up_prompt_template():
    aspect = make_aspect()
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    refiner.add_follow_up("Initial", "First answer")
    refiner.add_follow_up("Follow-up", "Second answer")

    prompt = refiner.format_follow_up_prompt_template("Original")

    assert "FOLLOW-UP CONTEXT" in prompt
    assert "Most recent user answer" in prompt
    assert "Second answer" in prompt
    assert "Respond in the following JSON format" in prompt


def test_query_aspect_refiner_can_ask_followup_respects_limits():
    aspect = make_aspect(allow_follow_up=True, max_follow_ups=1)
    refiner = QueryAspectRefiner(refinement_aspect=aspect)

    assert refiner.can_ask_followup()
    refiner.add_follow_up("Q1", "A1")
    assert not refiner.can_ask_followup()


def test_query_aspect_refiner_conversation_history_text():
    aspect = make_aspect()
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    assert refiner.get_conversation_history_text() == "no previous follow-up questions."

    refiner.add_follow_up("Question", "Answer")
    history = refiner.get_conversation_history_text()
    assert "Follow-up 1" in history
    assert "Question" in history
    assert "Answer" in history


# ---------------------------------------------------------------------------
# QueryRefinementSession behaviour
# ---------------------------------------------------------------------------

def build_session_with_steps():
    aspect_a = make_aspect(aspect_id="a", name="Aspect A")
    aspect_b = make_aspect(aspect_id="b", name="Aspect B", depends_on=["a"])

    session = QueryRefinementSession(original_query="original query")
    step_a = session.add_step(aspect_a)
    step_b = session.add_step(aspect_b)

    step_a.add_follow_up("Q", "Value A")
    step_a.is_complete = True

    return session, step_a, step_b


def test_session_get_active_step_prioritises_needs_review():
    session, step_a, step_b = build_session_with_steps()
    assert session.get_active_step() is step_b

    step_b.is_complete = True
    step_b.needs_review = True
    assert session.get_active_step() is step_b

    step_b.needs_review = False
    assert session.get_active_step() is None


def test_session_dependency_context_includes_values(caplog):
    session, step_a, step_b = build_session_with_steps()

    context = session.get_dependency_context("b")
    assert context["a"]["value"] == "Value A"

    with caplog.at_level("WARNING"):
        missing = session.get_dependency_context("unknown")
    assert missing == {}
    assert any("unknown refinement aspect" in record.message.lower() for record in caplog.records)


def test_session_is_complete_and_summary_counts():
    session, step_a, step_b = build_session_with_steps()
    summary = session.get_step_summary()
    assert summary["total_steps"] == 2
    assert summary["completed"] == 1
    assert summary["in_progress"] == 1
    assert not session.is_complete()

    step_b.is_complete = True
    assert session.is_complete()


def test_session_full_conversation_formatting():
    session, step_a, step_b = build_session_with_steps()
    step_b.add_follow_up("Question", "Answer")
    step_b.is_complete = True

    transcript = session.get_full_conversation()
    assert "Original Query" in transcript
    assert "[Aspect A]" in transcript
    assert "Q: Q" in transcript
    assert "A: Value A" in transcript
    assert "✓ Final value" in transcript


def test_session_handle_command_flow():
    session, step_a, step_b = build_session_with_steps()

    invalid = session.handle_command(CommandResult(command=UserCommand.NONE, is_valid=False, error_message="bad"))
    assert not invalid["success"] and invalid["message"] == "bad"

    goto_fail = session.handle_command(CommandResult(command=UserCommand.GOTO, argument=None))
    assert not goto_fail["success"]

    goto_invalid = session.handle_command(CommandResult(command=UserCommand.GOTO, argument="99"))
    assert not goto_invalid["success"]

    goto_success = session.handle_command(CommandResult(command=UserCommand.GOTO, argument="1"))
    assert goto_success["success"]
    assert goto_success["step_index"] == 0
    assert session.steps[0].follow_up_history == []  # Cleared when revisiting


def test_session_skip_and_finish_behaviour():
    aspect = make_aspect()
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)

    skip_result = session._skip_current()
    assert skip_result["success"]
    assert step.was_skipped

    finish_without_value = session._finish_current()
    assert finish_without_value["success"] is False
    assert step.was_skipped

    finish_session = QueryRefinementSession(original_query="query")
    finish_step = finish_session.add_step(make_aspect())
    finish_step.add_follow_up("Q", "A")
    finish = finish_session._finish_current()
    assert finish["success"]
    assert finish_step.is_complete


def test_session_back_restart_status_and_list():
    single_session = QueryRefinementSession(original_query="query")
    single_session.add_step(make_aspect())
    back_fail = single_session._go_back()
    assert not back_fail["success"]

    session, _, step_b = build_session_with_steps()
    step_b.add_follow_up("Q", "A")

    back_success = session._go_back()
    assert back_success["success"]
    assert back_success["step_index"] == 0
    assert not step_b.follow_up_history  # Cleared on revisit

    status = session._get_status()
    assert "Session Status" in status["message"]
    assert status["summary"]["total_steps"] == 2

    step_list = session._list_steps()
    assert "Refinement Steps" in step_list["message"]

    restart = session._restart()
    assert restart["success"]
    assert all(not step.follow_up_history for step in session.steps)


def test_session_request_synthesis_and_to_dict():
    session, step_a, step_b = build_session_with_steps()
    synth = session._request_synthesis()
    assert session.synthesis_requested
    assert synth["submit"]

    data = session.to_dict()
    assert data["original_query"] == "original query"
    assert len(data["steps"]) == 2


# ---------------------------------------------------------------------------
# QueryRefinementManager: initialization and step processing
# ---------------------------------------------------------------------------

def build_manager(responses: Iterable[Any], analysis_results: Dict[str, AspectAnalysisResult]) -> QueryRefinementManager:
    llm = StubLLMProvider(responses)
    analyzer = StubQueryAnalyzer(analysis_results)
    tracing = StubTracingProvider()
    return QueryRefinementManager(llm_provider=llm, query_analyzer=analyzer, tracing_provider=tracing)


def test_manager_initialize_applies_dependency_context():
    aspect_a = make_aspect(aspect_id="a", name="Aspect A")
    aspect_b = make_aspect(aspect_id="b", name="Aspect B", depends_on=["a"])

    manager = build_manager(
        responses=[],
        analysis_results={
            "a": AspectAnalysisResult(needs_refinement=False, explanation="Clear"),
            "b": AspectAnalysisResult(needs_refinement=True, explanation="Missing detail", suggested_question="Q2"),
        },
    )

    session = manager.initialize("Original query", [aspect_a, aspect_b])

    assert len(session.steps) == 2
    first, second = session.steps
    assert first.is_complete and first.initial_summary == "Clear"
    assert not second.is_complete

    # Dependency context for aspect B should include Aspect A value from original query (clear)
    ctx = session.get_dependency_context("b")
    assert ctx["a"]["value"].startswith("[Aspect A is clear")


def test_ensure_step_is_ready_autocompletes_dependent_aspect():
    aspect_a = make_aspect(aspect_id="a")
    aspect_b = make_aspect(aspect_id="b", depends_on=["a"])

    def analyze_b(context: Dict[str, Any]) -> AspectAnalysisResult:
        if "a" not in context:
            return AspectAnalysisResult(
                needs_refinement=True,
                explanation="Missing population",
                suggested_question="Provide population",
            )
        return AspectAnalysisResult(
            needs_refinement=False,
            explanation="Population context already specifies details",
        )

    manager = build_manager(
        responses=[],
        analysis_results={
            "a": AspectAnalysisResult(needs_refinement=False, explanation="Population covered"),
            "b": analyze_b,
        },
    )

    session = QueryRefinementSession(original_query="query")
    step_a = session.add_step(aspect_a)
    step_b = session.add_step(aspect_b)

    step_a.is_complete = True
    step_a.initial_summary = "Population captured in original query"

    step_b.is_complete = False
    step_b.analysis_suggested_question = "Need population"

    ready = manager.ensure_step_is_ready(session, step_b)

    assert not ready  # auto-resolved, no prompt needed
    assert step_b.is_complete
    assert "already" in (step_b.initial_summary or "").lower()


def test_dependency_context_uses_latest_follow_up_response():
    aspect_a = make_aspect(aspect_id="population")
    aspect_b = make_aspect(aspect_id="intervention", depends_on=["population"])

    session = QueryRefinementSession(original_query="query")
    step_a = session.add_step(aspect_a)
    session.add_step(aspect_b)

    step_a.add_follow_up("Q", "Adults aged 40-65")
    step_a.is_complete = True

    context = session.get_dependency_context("intervention")
    assert context["population"]["value"] == "Adults aged 40-65"


def test_process_next_step_returns_none_when_no_pending():
    manager = build_manager(responses=[], analysis_results={})
    session = QueryRefinementSession(original_query="query")

    assert manager.process_next_step(session) is None


def test_process_next_step_records_follow_up_without_schema():
    aspect = make_aspect()
    manager = build_manager(responses=["Answer"], analysis_results={})
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.analysis_suggested_question = "Question?"

    result = manager.process_next_step(session)

    assert result["response"] == "Answer"
    assert step.is_complete
    assert step.follow_up_history[-1]["response"] == "Answer"
    assert step.final_response == "Answer"


def test_process_next_step_enforces_json_validation():
    aspect = make_aspect(
        response_format={
            "additional_fields": {"confidence": "float"},
            "field_descriptions": {"confidence": "Confidence"},
        }
    )
    # First response invalid JSON, second valid
    responses = ["not json", json.dumps({"needs_refinement": False, "explanation": "ok", "suggested_question": "", "confidence": 0.9})]
    manager = build_manager(responses=responses, analysis_results={})
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.analysis_suggested_question = "Question?"

    result = manager.process_next_step(session)

    assert not result["error"]
    assert "structured_payload" in result
    assert result["structured_payload"]["confidence"] == 0.9
    # Ensure prompt was augmented
    augmented_prompt = manager.llm_provider.calls[1]["user_prompt"]
    assert "ATTEMPT 1" in augmented_prompt


def test_process_next_step_returns_error_after_failed_validation():
    aspect = make_aspect(
        response_format={"additional_fields": {"score": "float"}}
    )
    responses = ["not json", "still not json", "invalid again"]
    manager = build_manager(responses=responses, analysis_results={})
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.analysis_suggested_question = "Question?"

    result = manager.process_next_step(session)

    assert result["error"]
    assert "Validation error" in result["response"]
    assert step.is_complete


def test_augment_prompt_for_retry_appends_guidance():
    prompt = QueryRefinementManager._augment_prompt_for_retry("base", "not json", 1, "previous")
    assert "ATTEMPT 1" in prompt
    assert "not json" in prompt
    assert "previous" in prompt


def test_build_follow_up_prompts_requires_history():
    manager = build_manager(responses=[], analysis_results={})
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(make_aspect())

    with pytest.raises(ValueError):
        manager.build_follow_up_prompts(session)

    step.add_follow_up("Q", "A")
    system_prompt, user_prompt = manager.build_follow_up_prompts(session)
    assert "FOLLOW-UP CONTEXT" in user_prompt
    assert system_prompt.startswith("You refine")


def test_gather_refinement_details_compiles_lists():
    manager = build_manager(responses=[], analysis_results={})
    session = QueryRefinementSession(original_query="query")

    aspect1 = make_aspect(aspect_id="a", name="A")
    aspect2 = make_aspect(aspect_id="b", name="B")

    step1 = session.add_step(aspect1)
    step1.add_follow_up("Q", "Value")
    step1.is_complete = True

    step2 = session.add_step(aspect2)
    step2.is_complete = True
    step2.initial_summary = "Already clear"

    clarifications, summaries = manager._gather_refinement_details(session)
    assert clarifications == [("A", "Value")]
    assert summaries == [("B", "Already clear")]


def test_synthesize_refined_query_without_clarifications():
    manager = build_manager(responses=[], analysis_results={})
    session = QueryRefinementSession(original_query="original")

    result = manager.synthesize_refined_query(session)
    assert not result["used_llm"]
    assert result["refined_query"] == "original"


def test_synthesize_refined_query_with_clarifications():
    aspect = make_aspect(aspect_id="a", name="Population")
    llm_response = "Refined query"
    manager = build_manager(responses=[llm_response], analysis_results={})
    session = QueryRefinementSession(original_query="original query")
    step = session.add_step(aspect)
    step.add_follow_up("Q", "Adults 18-65")
    step.is_complete = True

    result = manager.synthesize_refined_query(session)
    assert result["used_llm"]
    assert result["refined_query"] == "Refined query"
    call = manager.llm_provider.calls[0]
    assert "ORIGINAL QUERY" in call["user_prompt"]
    assert "Adults 18-65" in call["user_prompt"]


def test_run_full_refinement_processes_steps():
    aspect = make_aspect()
    manager = build_manager(responses=["answer"], analysis_results={})
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.analysis_suggested_question = "Q"

    manager.run_full_refinement(session)
    assert step.is_complete


def test_get_initialization_summary_orders_results():
    aspect_a = make_aspect(aspect_id="a", name="A")
    aspect_b = make_aspect(aspect_id="b", name="B")

    manager = build_manager(
        responses=[],
        analysis_results={
            "a": AspectAnalysisResult(needs_refinement=False, explanation="Clear"),
            "b": AspectAnalysisResult(needs_refinement=True, explanation="Need more", suggested_question="Q"),
        },
    )

    session = manager.initialize("query", [aspect_a, aspect_b])
    summary = manager.get_initialization_summary(session)

    assert summary["total_aspects"] == 2
    assert summary["aspects_needing_refinement"] == 1
    assert summary["aspects_clear"] == 1
    statuses = [aspect_info["status"] for aspect_info in summary["aspects"]]
    assert statuses.count("needs_refinement") == 1
    assert any("suggested_question" in info for info in summary["aspects"] if info["status"] == "needs_refinement")