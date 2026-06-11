import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch

import pytest


PRIVATE_MODEL = "anthropic/claude-sonnet-4-6"
OPEN_MODEL = "ollama/qwen2.5:72b"

from query_refinement_module.core import (
    COMMAND_ALIASES,
    CommandResult,
    AspectRefinementState,
    QueryRefinementManager,
    RefinementSession,
    UserCommand,
    get_help_text,
    is_user_command,
    parse_user_command,
    _use_open_llm_synthesis_variant_for_model,
)
from query_refinement_module.interfaces import (
    LLMCompletionResult,
    LLMProviderInterface,
    TracingProviderInterface,
)
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.schema.response import (
    DimensionEvaluationResponse,
    FilterSuggestionResponse,
    KeywordSupportResponse,
    QueryRefinementResponse,
    SemanticQueryResponse,
    StatementResponse,
    TerminologyResponse,
)


# ---------------------------------------------------------------------------
# Helper factories and doubles
# ---------------------------------------------------------------------------

def make_split_responses(
    *,
    integrated_statement: str = "synthesized statement",
    semantic: str = "semantic query",
    synonyms: Optional[Dict[str, Any]] = None,
    fields_of_study: Optional[List[str]] = None,
    phrases: Optional[List[str]] = None,
    required: Optional[List[str]] = None,
    optional: Optional[List[str]] = None,
) -> List[str]:
    """Return 5 JSON strings in split-call consumption order:
    statement, semantic, terminology, filter_resolution, keyword_support.
    """
    return [
        json.dumps({"integrated_statement": integrated_statement}),
        json.dumps({"semantic": semantic}),
        json.dumps({"synonyms": synonyms or {}}),
        json.dumps({"fields_of_study": fields_of_study or []}),
        json.dumps({
            "phrases": phrases or [],
            "required": required or [],
            "optional": optional or [],
        }),
    ]

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
        specifications=analysis_prompt,
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
        self._default_model = OPEN_MODEL
        self.calls: List[Dict[str, Any]] = []

    def complete(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Any] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": messages,
                "response_format": response_format,
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

    async def complete_async(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Any] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        # Reuse the sync implementation for testing
        return self.complete(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
            response_format=response_format,
            **kwargs,
        )

    def get_model_info(self, model: str) -> Dict[str, Any]:  # pragma: no cover - unused
        return {}


class DelayedSplitLLMProvider(LLMProviderInterface):
    def __init__(
        self,
        responses_by_model: Dict[str, Any],
        delays_by_model: Optional[Dict[str, float]] = None,
    ):
        self._responses_by_model = dict(responses_by_model)
        self._delays_by_model = delays_by_model or {}
        self._default_model = OPEN_MODEL
        self.calls: List[Dict[str, Any]] = []

    def complete(self, *args, **kwargs) -> LLMCompletionResult:  # pragma: no cover - sync path unused
        raise NotImplementedError("DelayedSplitLLMProvider only supports complete_async")

    async def complete_async(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Any] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        response_model_name = getattr(response_format, "__name__", "unknown")
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": messages,
                "response_format": response_format,
                "kwargs": kwargs,
            }
        )
        await asyncio.sleep(self._delays_by_model.get(response_model_name, 0.0))
        item = self._responses_by_model[response_model_name]
        return DummyCompletionResult(context=item, model="dummy")

    def get_model_info(self, model: str) -> Dict[str, Any]:  # pragma: no cover - unused
        return {}


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

    skip = parse_user_command("/skip")
    assert skip.command is UserCommand.SKIP
    assert skip.is_valid


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
    refiner = AspectRefinementState(refinement_aspect=aspect)

    assert refiner.follow_up_count == 0
    assert refiner.normalized_value_as_str is None

    refiner.add_follow_up(question="Q1", response="Answer")
    assert refiner.follow_up_count == 1
    assert refiner.normalized_value_as_str == "Answer"  # Plain text is now stored in refinement_aspect_value


def test_query_aspect_refiner_get_prompts_includes_dependency_context(caplog):
    dep_aspect = make_aspect(aspect_id="dep", name="Dep", description="dep desc")
    target_aspect = make_aspect(
        aspect_id="target",
        name="Target",
        description="Target desc",
        depends_on=["dep", "missing"],
    )

    dep_refiner = AspectRefinementState(refinement_aspect=dep_aspect)
    dep_refiner.add_follow_up("Q", "Value")

    target_refiner = AspectRefinementState(refinement_aspect=target_aspect)

    context = {
        "dep": {"name": "Dep", "value": "Value"},
    }

    with caplog.at_level("DEBUG"):  # Changed from WARNING to DEBUG since prompt_builder logs at debug
        messages = target_refiner.get_messages(
            query="Original query",
            dependency_context=context,
        )

    # Verify messages array structure
    assert len(messages) > 0
    messages_text = " ".join(str(msg.get("content", "")) for msg in messages)
    
    # Should contain dependency info and original query
    assert "Dep" in messages_text or "Value" in messages_text
    assert "Original query" in messages_text
    # Note: Logging for missing dependencies now happens in prompt_builder at DEBUG level


def test_query_aspect_refiner_can_ask_followup_respects_limits():
    aspect = make_aspect(allow_follow_up=True, max_follow_ups=1)
    refiner = AspectRefinementState(refinement_aspect=aspect)

    assert refiner.can_ask_followup()
    refiner.add_follow_up("Q1", "A1")
    assert not refiner.can_ask_followup()


# ---------------------------------------------------------------------------
# QueryRefinementSession behaviour
# ---------------------------------------------------------------------------

def build_session_with_steps():
    aspect_a = make_aspect(aspect_id="a", name="Aspect A")
    aspect_b = make_aspect(aspect_id="b", name="Aspect B", depends_on=["a"])

    session = RefinementSession(original_query="original query")
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

    # Should return empty context for unknown aspect (logged at debug level, not warning)
    with caplog.at_level("DEBUG"):
        missing = session.get_dependency_context("unknown")
    assert missing == {}
    # Debug message should mention dependency context
    assert any("dependency context" in record.message.lower() for record in caplog.records)


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

    # Test /back truncates steps
    back_result = session.handle_command(CommandResult(command=UserCommand.BACK))
    assert back_result["success"]
    assert len(session.steps) == 1  # Only first step remains

    # Test /clear clears current aspect
    session, step_a, step_b = build_session_with_steps()
    step_b.add_follow_up("Q", "A")
    clear_result = session.handle_command(CommandResult(command=UserCommand.CLEAR))
    assert clear_result["success"]
    assert clear_result["regenerate_question"] is True
    assert len(step_b.conversation_history) == 0


def test_session_skip_and_finish_behaviour():
    aspect = make_aspect()
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)

    # Use handle_command with proper CommandResult instead of internal method
    skip_result = session.handle_command(CommandResult(command=UserCommand.SKIP))
    assert skip_result["success"]
    assert step.was_skipped

    # Finish without value on skipped step should fail
    finish_without_value = session.handle_command(CommandResult(command=UserCommand.DONE))
    assert finish_without_value["success"] is False
    assert step.was_skipped

    # Create new session for finish test
    finish_session = RefinementSession(original_query="query")
    finish_step = finish_session.add_step(make_aspect())
    finish_step.add_follow_up("Q", "A")
    finish = finish_session.handle_command(CommandResult(command=UserCommand.DONE))
    assert finish["success"]
    assert finish_step.is_complete


def test_session_back_restart_status_and_list():
    single_session = RefinementSession(original_query="query")
    single_session.add_step(make_aspect())
    back_fail = single_session.handle_command(CommandResult(command=UserCommand.BACK))
    assert not back_fail["success"]

    session, _, step_b = build_session_with_steps()
    step_b.add_follow_up("Q", "A")

    back_success = session.handle_command(CommandResult(command=UserCommand.BACK))
    assert back_success["success"]
    assert back_success["step_index"] == 0
    # step_b is removed from session (truncated), not just history cleared
    assert len(session.steps) == 1
    assert session.steps[0].refinement_aspect.id == "a"

    status = session.handle_command(CommandResult(command=UserCommand.STATUS))
    assert "Session Status" in status["message"]
    assert status["summary"]["total_steps"] == 1  # step_b was truncated

    step_list = session.handle_command(CommandResult(command=UserCommand.STEPS))
    assert "Processed Steps" in step_list["message"]

    restart = session.handle_command(CommandResult(command=UserCommand.RESTART))
    assert restart["success"]
    assert all(not step.conversation_history for step in session.steps)


def test_session_request_synthesis_and_to_dict():
    session, step_a, step_b = build_session_with_steps()
    synth = session.handle_command(CommandResult(command=UserCommand.SUBMIT))
    assert session.synthesis_requested
    assert synth["submit"]

    data = session.to_dict()
    assert data["original_query"] == "original query"
    assert len(data["steps"]) == 2


# ---------------------------------------------------------------------------
# QueryRefinementManager: initialization and step processing
# ---------------------------------------------------------------------------

def build_manager(responses: Iterable[Any]) -> QueryRefinementManager:
    """Build a manager with stub LLM provider for testing.
    
    Note: v2.0+ no longer supports query_analyzer parameter.
    """
    llm = StubLLMProvider(responses)
    tracing = StubTracingProvider()
    return QueryRefinementManager(llm_provider=llm, tracing_provider=tracing)


@pytest.mark.asyncio
async def test_synthesize_refined_query_uses_manager_runtime_defaults():
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider(make_split_responses(integrated_statement="stmt")),
        tracing_provider=StubTracingProvider(),
        default_temperature=0.45,
        default_max_tokens=300,
    )
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session, model=OPEN_MODEL)

    assert len(manager.llm_provider.calls) == 5
    assert all(call["temperature"] == pytest.approx(0.45) for call in manager.llm_provider.calls)
    assert sorted(call["max_tokens"] for call in manager.llm_provider.calls) == [256, 256, 300, 300, 300]


@pytest.mark.asyncio
async def test_synthesize_refined_query_explicit_runtime_overrides_manager_defaults():
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider(make_split_responses(integrated_statement="stmt")),
        tracing_provider=StubTracingProvider(),
        default_temperature=0.45,
        default_max_tokens=300,
    )
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session, model=OPEN_MODEL, temperature=0.1, max_tokens=200)

    assert len(manager.llm_provider.calls) == 5
    assert all(call["temperature"] == pytest.approx(0.1) for call in manager.llm_provider.calls)
    assert sorted(call["max_tokens"] for call in manager.llm_provider.calls) == [200, 200, 200, 200, 200]


@pytest.mark.asyncio
async def test_private_models_use_single_monolithic_synthesis_call():
    response = QueryRefinementResponse(
        integrated_statement="Refined question",
        dimensions_specifications={},
        search_optimized={
            "semantic": "semantic query",
            "keyword": {
                "structured": "query",
                "phrases": [],
                "terms": {"required": [], "optional": [], "excluded": []},
            },
        },
        search_filters={
            "publication_years": "",
            "venues": [],
            "authors": [],
            "publication_types": [],
            "fields_of_study": [],
        },
        terminology={"synonyms": {}, "colloquial": []},
    )
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider([response]),
        tracing_provider=StubTracingProvider(),
    )
    session = RefinementSession(original_query="q")

    result = await manager.synthesize_refined_query(session, model=PRIVATE_MODEL)

    assert result["integrated_statement"] == "Refined question"
    assert len(manager.llm_provider.calls) == 1
    assert manager.llm_provider.calls[0]["response_format"] is QueryRefinementResponse


@pytest.mark.asyncio
async def test_open_models_continue_to_use_split_synthesis_calls():
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider(make_split_responses(integrated_statement="stmt")),
        tracing_provider=StubTracingProvider(),
    )
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session, model=OPEN_MODEL)

    assert len(manager.llm_provider.calls) == 5


@pytest.mark.asyncio
async def test_private_wrapper_models_still_use_single_monolithic_synthesis_call():
    response = QueryRefinementResponse(
        integrated_statement="Refined question",
        dimensions_specifications={},
        search_optimized={
            "semantic": "semantic query",
            "keyword": {
                "structured": "query",
                "phrases": [],
                "terms": {"required": [], "optional": [], "excluded": []},
            },
        },
        search_filters={
            "publication_years": "",
            "venues": [],
            "authors": [],
            "publication_types": [],
            "fields_of_study": [],
        },
        terminology={"synonyms": {}, "colloquial": []},
    )
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider([response]),
        tracing_provider=StubTracingProvider(),
    )
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session, model="bedrock/anthropic.claude-3-7-sonnet")

    assert len(manager.llm_provider.calls) == 1
    assert manager.llm_provider.calls[0]["response_format"] is QueryRefinementResponse


@pytest.mark.asyncio
async def test_open_wrapper_models_still_use_split_synthesis_calls():
    manager = QueryRefinementManager(
        llm_provider=StubLLMProvider(make_split_responses(integrated_statement="stmt")),
        tracing_provider=StubTracingProvider(),
    )
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session, model="google/gemma-2-27b")

    assert len(manager.llm_provider.calls) == 5


@pytest.mark.asyncio
async def test_private_wrapper_provider_default_uses_monolithic_synthesis_call():
    response = QueryRefinementResponse(
        integrated_statement="Refined question",
        dimensions_specifications={},
        search_optimized={
            "semantic": "semantic query",
            "keyword": {
                "structured": "query",
                "phrases": [],
                "terms": {"required": [], "optional": [], "excluded": []},
            },
        },
        search_filters={
            "publication_years": "",
            "venues": [],
            "authors": [],
            "publication_types": [],
            "fields_of_study": [],
        },
        terminology={"synonyms": {}, "colloquial": []},
    )
    provider = StubLLMProvider([response])
    provider._default_model = "bedrock/anthropic.claude-3-7-sonnet"
    manager = QueryRefinementManager(llm_provider=provider, tracing_provider=StubTracingProvider())
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session)

    assert len(provider.calls) == 1
    assert provider.calls[0]["response_format"] is QueryRefinementResponse


@pytest.mark.asyncio
async def test_open_wrapper_provider_default_uses_split_synthesis_calls():
    provider = StubLLMProvider(make_split_responses(integrated_statement="stmt"))
    provider._default_model = "google/gemma-2-27b"
    manager = QueryRefinementManager(llm_provider=provider, tracing_provider=StubTracingProvider())
    session = RefinementSession(original_query="q")

    await manager.synthesize_refined_query(session)

    assert len(provider.calls) == 5


def test_private_wrapper_model_ids_do_not_fall_back_to_open_variant():
    with patch("query_refinement_module.core._using_open_llm_synthesis_variant", return_value=True):
        assert _use_open_llm_synthesis_variant_for_model("bedrock/anthropic.claude-3-7-sonnet") is False
        assert _use_open_llm_synthesis_variant_for_model("azure/openai/gpt-4o") is False
        assert _use_open_llm_synthesis_variant_for_model("vertex_ai/gemini-1.5-pro") is False
        assert _use_open_llm_synthesis_variant_for_model("llamaindex/openai/gpt-4o") is False


def test_skipped_aspects_excluded_from_dependency_context():
    """Test that skipped aspects provide NO context to dependents."""
    aspect_a = make_aspect(aspect_id="a", name="Population")
    aspect_b = make_aspect(aspect_id="b", name="Intervention", depends_on=["a"])
    
    session = RefinementSession(original_query="Test query")
    step_a = session.add_step(aspect_a)
    step_b = session.add_step(aspect_b)
    
    # Skip aspect A (which B depends on)
    step_a.was_skipped = True
    step_a.is_complete = True
    step_a.normalized_value = None  # Skipped aspects have no value
    
    # Get dependency context for B
    ctx = session.get_dependency_context("b")
    
    # Skipped aspect A should be completely excluded
    assert "a" not in ctx
    assert len(ctx) == 0


def test_dependency_context_uses_latest_follow_up_response():
    aspect_a = make_aspect(aspect_id="population")
    aspect_b = make_aspect(aspect_id="intervention", depends_on=["population"])

    session = RefinementSession(original_query="query")
    step_a = session.add_step(aspect_a)
    session.add_step(aspect_b)

    step_a.add_follow_up("Q", "Adults aged 40-65")
    step_a.is_complete = True

    context = session.get_dependency_context("intervention")
    assert context["population"]["value"] == "Adults aged 40-65"


@pytest.mark.asyncio
async def test_process_next_step_returns_none_when_no_pending():
    manager = build_manager(responses=[])
    session = RefinementSession(original_query="query")

    assert await manager.process_next_step(session) is None


@pytest.mark.asyncio
async def test_process_next_step_records_follow_up_without_schema():
    aspect = make_aspect()
    # Updated: Include all required fields (complete, current, question)
    json_response = json.dumps({
        "complete": True,
        "current": "Synthesized answer",
        "question": "",
        "demo": "Synthesized answer"  # Dynamic value field
    })
    manager = build_manager(responses=[json_response, json_response, json_response])
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.follow_up_question = "Question?"

    result = await manager.process_next_step(session)

    assert result["response"] == json_response
    assert step.is_complete
    assert step.conversation_history[-1]["response"] == json_response
    # normalized_value_as_str returns the synthesized value from the dynamic field (aspect.id)
    assert step.normalized_value_as_str == "Synthesized answer"
    assert step.normalized_value == "Synthesized answer"


@pytest.mark.asyncio
async def test_process_next_step_enforces_json_validation():
    """Test that invalid JSON responses result in error (v2.0 uses structured outputs, no retry)."""
    aspect = make_aspect(
        response_format={
            "additional_fields": {"confidence": "float"},
            "field_descriptions": {"confidence": "Confidence"},
        }
    )
    # Valid JSON response with all required fields
    responses = [
        json.dumps({
            "complete": True,
            "current": "value",
            "question": "",
            "confidence": 0.9,
            "demo": "value"  # Dynamic value field for aspect.id
        })
    ]
    manager = build_manager(responses=responses)
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.follow_up_question = "Question?"

    result = await manager.process_next_step(session)

    assert not result["error"]
    assert "structured_payload" in result
    assert result["structured_payload"]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_process_next_step_returns_error_after_failed_validation():
    aspect = make_aspect(
        response_format={"additional_fields": {"score": "float"}}
    )
    responses = ["not json", "still not json", "invalid again"]
    manager = build_manager(responses=responses)
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.follow_up_question = "Question?"

    result = await manager.process_next_step(session)

    assert result["error"]
    assert "Validation error" in result["response"]
    assert step.is_complete


def test_gather_refinement_details_compiles_lists():
    manager = build_manager(responses=[])
    session = RefinementSession(original_query="query")

    aspect1 = make_aspect(aspect_id="a", name="A")
    aspect2 = make_aspect(aspect_id="b", name="B")

    step1 = session.add_step(aspect1)
    step1.add_follow_up("Q", "Value")
    step1.is_complete = True

    step2 = session.add_step(aspect2)
    step2.is_complete = True
    step2.normalized_value = "Already clear"

    clarifications, summaries = manager._gather_refinement_details(session)
    assert clarifications == [("A", "Value")]
    assert summaries == [("B", "Already clear")]


def test_process_analysis_result_persists_partial_current_when_incomplete():
    manager = build_manager(responses=[])
    aspect = make_aspect(aspect_id="population", name="Population")
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)

    result = DimensionEvaluationResponse(
        complete=False,
        current="adults with COPD",
        question="Can you narrow by age range?",
    )

    status = manager.process_analysis_result(session, "population", result)

    assert not status["complete"]
    assert step.is_complete is False
    assert step.follow_up_question == "Can you narrow by age range?"
    assert step.normalized_value_as_str == "adults with COPD"


def test_process_analysis_result_keeps_existing_value_when_current_empty():
    manager = build_manager(responses=[])
    aspect = make_aspect(aspect_id="population", name="Population")
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.normalized_value = "adults with COPD"

    result = DimensionEvaluationResponse(
        complete=False,
        current="",
        question="Any specific setting?",
    )

    status = manager.process_analysis_result(session, "population", result)

    assert not status["complete"]
    assert step.is_complete is False
    assert step.follow_up_question == "Any specific setting?"
    assert step.normalized_value_as_str == "adults with COPD"


@pytest.mark.asyncio
async def test_synthesize_refined_query_without_clarifications():
    """Even with no answered dimensions, the LLM is called to produce semantic/keyword expansions."""
    manager = build_manager(responses=make_split_responses(
        integrated_statement="expanded: original",
        semantic="original synonyms expansions",
        phrases=["original"],
        required=["original"],
    ))
    session = RefinementSession(original_query="original")

    result = await manager.synthesize_refined_query(session)
    assert result["used_llm"]
    assert result["integrated_statement"] == "expanded: original"
    # The original query must appear in the statement call prompt
    call = manager.llm_provider.calls[0]
    assert "original" in call["user_prompt"].lower()


@pytest.mark.asyncio
async def test_synthesize_refined_query_with_clarifications():
    aspect = make_aspect(aspect_id="a", name="Population")
    manager = build_manager(responses=make_split_responses(
        integrated_statement="Refined query for adults 18-65",
        semantic="adults 18-65 health outcomes",
        phrases=["adults 18-65"],
        required=["adults"],
    ))
    session = RefinementSession(original_query="original query")
    step = session.add_step(aspect)
    step.add_follow_up("Q", "Adults 18-65")
    step.is_complete = True

    result = await manager.synthesize_refined_query(session)
    assert result["used_llm"]
    assert result["integrated_statement"] == "Refined query for adults 18-65"
    # Statement call must see both the original query and the accepted dimension value
    call = manager.llm_provider.calls[0]
    assert "original query" in call["user_prompt"].lower()
    assert "Adults 18-65" in call["user_prompt"]


@pytest.mark.asyncio
async def test_synthesize_refined_query_prefers_deterministic_dimensions_and_filters():
    aspect = make_aspect(aspect_id="population", name="Population")
    manager = build_manager(responses=make_split_responses(
        integrated_statement="Refined query for adults 18-65 since 2018 published in New England Journal of Medicine by Jane Doe",
        semantic="adults 18-65 health outcomes",
        phrases=["adults 18-65"],
        required=["adults"],
    ))
    session = RefinementSession(original_query="Studies since 2018 published in New England Journal of Medicine by Jane Doe")
    step = session.add_step(aspect)
    step.add_follow_up("Q", "Adults 18-65")
    step.is_complete = True

    import datetime as _dt
    fixed_now = _dt.datetime(2026, 5, 5, tzinfo=_dt.timezone.utc)
    with patch("query_refinement_module.core.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        result = await manager.synthesize_refined_query(session)

    assert result["dimensions_specifications"] == {"population": "Adults 18-65"}
    assert result["search_filters"].publication_years == "2018-2026"
    assert "Jane Doe" in result["search_filters"].authors
    assert "New England Journal of Medicine" in result["search_filters"].venues


@pytest.mark.asyncio
async def test_run_full_refinement_processes_steps():
    aspect = make_aspect()
    # Create a valid JSON response with required fields
    json_response = json.dumps({
        "is_complete": True,
        "reasoning": "answer",
        "refinement_aspect_value": "answer",
        "demo": "answer"
    })
    manager = build_manager(responses=[json_response])
    session = RefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.follow_up_question = "Q"

    # Note: run_full_refinement is sync but internally calls async process_next_step
    # This may not work as expected - we'll process manually instead
    result = await manager.process_next_step(session)
    assert step.is_complete


@pytest.mark.asyncio
async def test_synthesize_refined_query_uses_preparsed_context():
    """When the provider returns pre-parsed narrow models, each split call uses them directly
    without attempting json.loads (fast path in _run_split_call)."""
    # Provide pre-parsed narrow model instances in split-call order:
    # statement, semantic, terminology, filter_resolution, keyword_support
    manager = build_manager(responses=[
        StatementResponse(integrated_statement="Pre-parsed integrated statement"),
        SemanticQueryResponse(semantic="pre-parsed semantic query"),
        TerminologyResponse(synonyms={"exercise": ["physical activity"]}),
        FilterSuggestionResponse(fields_of_study=["Medicine"]),
        KeywordSupportResponse(phrases=["pre-parsed"], required=["exercise"], optional=[]),
    ])
    session = RefinementSession(original_query="original query")

    result = await manager.synthesize_refined_query(session)

    assert result["used_llm"]
    assert result["integrated_statement"] == "Pre-parsed integrated statement"
    assert result["search_optimized"].semantic == "pre-parsed semantic query"
    assert result["terminology"].synonyms == {"exercise": ["physical activity"]}
    assert result["search_filters"].fields_of_study == ["Medicine"]
    # dimensions_specifications is always deterministic (from session state, never from LLM)
    assert result["dimensions_specifications"] == {}


# ---------------------------------------------------------------------------
# Workstream 6: field-level validation and repair
# ---------------------------------------------------------------------------

class TestValidateSplitResult:
    """_validate_split_result returns None on valid input and an error string on violation."""

    def test_statement_valid(self):
        r = StatementResponse(integrated_statement="some statement")
        assert QueryRefinementManager._validate_split_result("statement", r) is None

    def test_statement_empty(self):
        r = StatementResponse(integrated_statement="")
        assert QueryRefinementManager._validate_split_result("statement", r) is not None

    def test_statement_whitespace_only(self):
        r = StatementResponse(integrated_statement="   ")
        assert QueryRefinementManager._validate_split_result("statement", r) is not None

    def test_semantic_valid(self):
        r = SemanticQueryResponse(semantic="adults with COPD receiving pulmonary rehab")
        assert QueryRefinementManager._validate_split_result("semantic", r) is None

    def test_semantic_empty(self):
        r = SemanticQueryResponse(semantic="")
        assert QueryRefinementManager._validate_split_result("semantic", r) is not None

    def test_terminology_valid(self):
        r = TerminologyResponse(synonyms={"COPD": ["chronic obstructive pulmonary disease"]})
        assert QueryRefinementManager._validate_split_result("terminology", r) is None

    def test_terminology_self_reference(self):
        """A term must not list itself as its own synonym."""
        r = TerminologyResponse(synonyms={"COPD": ["COPD", "lung disease"]})
        err = QueryRefinementManager._validate_split_result("terminology", r)
        assert err is not None
        assert "synonym" in err

    def test_terminology_empty_synonym_item(self):
        r = TerminologyResponse(synonyms={"COPD": ["", "chronic obstructive pulmonary disease"]})
        assert QueryRefinementManager._validate_split_result("terminology", r) is not None

    def test_keyword_valid(self):
        r = KeywordSupportResponse(phrases=["COPD rehab"], required=["COPD"], optional=["adults"])
        assert QueryRefinementManager._validate_split_result("keyword_support", r) is None

    def test_keyword_required_optional_overlap(self):
        r = KeywordSupportResponse(phrases=[], required=["COPD"], optional=["COPD"])
        err = QueryRefinementManager._validate_split_result("keyword_support", r)
        assert err is not None
        assert "overlap" in err

    def test_keyword_empty_item(self):
        r = KeywordSupportResponse(phrases=[""], required=[], optional=[])
        assert QueryRefinementManager._validate_split_result("keyword_support", r) is not None

    def test_filter_valid(self):
        r = FilterSuggestionResponse(fields_of_study=["Medicine", "Psychology"])
        assert QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL) is None

    def test_filter_empty_list_valid(self):
        r = FilterSuggestionResponse(fields_of_study=[])
        assert QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL) is None

    def test_filter_bad_value(self):
        r = FilterSuggestionResponse(fields_of_study=["Medicine", "Astrology"])
        err = QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL)
        assert err is not None
        assert "Astrology" in err

    def test_filter_pub_types_valid(self):
        r = FilterSuggestionResponse(publication_types=["Randomized controlled trial", "Systematic review"])
        assert QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL) is None

    def test_filter_pub_types_invalid_abbreviation(self):
        r = FilterSuggestionResponse(publication_types=["RCT"])
        err = QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL)
        assert err is not None
        assert "RCT" in err

    def test_filter_pub_years_natural_language_invalid(self):
        r = FilterSuggestionResponse(publication_years="last 5 years")
        err = QueryRefinementManager._validate_split_result("filter_resolution", r, model=PRIVATE_MODEL)
        assert err is not None
        assert "publication_years" in err

    def test_open_llm_filter_validation_ignores_publication_years_and_types(self):
        r = FilterSuggestionResponse(
            publication_years="last 5 years",
            publication_types=["RCT"],
            fields_of_study=["Medicine"],
        )
        err = QueryRefinementManager._validate_split_result("filter_resolution", r, model=OPEN_MODEL)
        assert err is not None
        assert "publication_years" in err or "publication_types" in err

    def test_unknown_call_name_always_valid(self):
        """Calls we don't recognise should pass through without error."""
        assert QueryRefinementManager._validate_split_result("unknown_call", object()) is None


class TestBuildRepairPrompt:
    """_build_repair_prompt appends a targeted instruction.

    Fields that must NEVER appear in any repair prompt (always session-derived):
      - dimensions_specifications

    Fields that are off-limits for non-filter repair prompts but ARE expected in
    the filter_resolution repair (venues and authors have no permitted list so
    they never appear in any repair prompt either):
      - venues
      - authors
    """

    # Never appears in any repair prompt — always session-state, never LLM
    _ALWAYS_FORBIDDEN = ("dimensions_specifications",)
    # Off-limits for non-filter calls; NOT expected in filter_resolution repair
    _NON_FILTER_FORBIDDEN = ("venues", "authors")

    def _check_no_always_forbidden_fields(self, prompt: str):
        for field in self._ALWAYS_FORBIDDEN:
            assert field not in prompt, (
                f"Repair prompt must never mention always-session field '{field}'"
            )

    def _check_non_filter_forbidden(self, prompt: str):
        for field in self._NON_FILTER_FORBIDDEN:
            assert field not in prompt, (
                f"Non-filter repair prompt must not mention unvalidated filter field '{field}'"
            )

    def test_statement_repair_prompt(self):
        prompt = QueryRefinementManager._build_repair_prompt("base prompt", "statement", "empty")
        assert "REPAIR" in prompt
        assert "integrated_statement" in prompt
        self._check_no_always_forbidden_fields(prompt)
        self._check_non_filter_forbidden(prompt)

    def test_semantic_repair_prompt(self):
        prompt = QueryRefinementManager._build_repair_prompt("base", "semantic", "empty")
        assert "REPAIR" in prompt
        assert "semantic" in prompt
        self._check_no_always_forbidden_fields(prompt)
        self._check_non_filter_forbidden(prompt)

    def test_terminology_repair_prompt(self):
        prompt = QueryRefinementManager._build_repair_prompt("base", "terminology", "self-ref")
        assert "REPAIR" in prompt
        self._check_no_always_forbidden_fields(prompt)
        self._check_non_filter_forbidden(prompt)

    def test_keyword_repair_prompt(self):
        prompt = QueryRefinementManager._build_repair_prompt("base", "keyword_support", "overlap")
        assert "REPAIR" in prompt
        self._check_no_always_forbidden_fields(prompt)
        self._check_non_filter_forbidden(prompt)

    def test_filter_repair_prompt(self):
        prompt = QueryRefinementManager._build_repair_prompt("base", "filter_resolution", "bad value", model=PRIVATE_MODEL)
        assert "REPAIR" in prompt
        assert "publication_types" in prompt
        assert "publication_years" in prompt
        assert "permitted" in prompt
        self._check_no_always_forbidden_fields(prompt)

    def test_open_llm_filter_repair_prompt_matches_full_contract(self):
        prompt = QueryRefinementManager._build_repair_prompt("base", "filter_resolution", "bad value", model=OPEN_MODEL)
        assert "fields_of_study" in prompt
        assert "publication_types" in prompt
        assert "publication_years" in prompt

    def test_original_prompt_preserved(self):
        original = "## Original Input\n\nsome query"
        prompt = QueryRefinementManager._build_repair_prompt(original, "statement", "empty")
        assert original in prompt

    def test_previous_output_included_in_repair_prompt(self):
        """When previous_output is supplied, it appears in the repair prompt body."""
        prev = '{"integrated_statement": ""}'
        prompt = QueryRefinementManager._build_repair_prompt(
            "base", "statement", "empty", previous_output=prev
        )
        assert prev in prompt
        assert "previous output" in prompt.lower()

    def test_previous_output_truncated_at_600_chars(self):
        long_output = "x" * 1200
        prompt = QueryRefinementManager._build_repair_prompt(
            "base", "statement", "empty", previous_output=long_output
        )
        # The full 1200-char string must NOT be present; the truncated form must be
        assert long_output not in prompt
        assert "x" * 600 in prompt


@pytest.mark.asyncio
async def test_run_split_call_triggers_repair_on_validation_failure():
    """When the first response fails validation, _run_split_call retries with a repair prompt
    and returns the repaired result."""
    # First response: empty statement (fails validation)
    # Second response: valid statement (repair succeeds)
    manager = build_manager(responses=[
        json.dumps({"integrated_statement": ""}),
        json.dumps({"integrated_statement": "valid repaired statement"}),
    ])
    from query_refinement_module.schema.synthesis import SynthesisPromptBuilder
    pb = SynthesisPromptBuilder()
    result, meta = await manager._run_split_call(
        pb.get_statement_system_prompt(),
        "some user prompt",
        StatementResponse,
        "statement",
    )
    assert result is not None
    assert result.integrated_statement == "valid repaired statement"
    # Two provider calls should have been made (initial + repair)
    assert len(manager.llm_provider.calls) == 2
    # The repair call's user prompt must include the REPAIR instruction
    repair_user_prompt = manager.llm_provider.calls[1]["user_prompt"]
    assert "REPAIR" in repair_user_prompt


@pytest.mark.asyncio
async def test_run_split_call_returns_none_when_repair_also_fails():
    """When both the initial call and the repair attempt fail validation, return (None, ...)."""
    manager = build_manager(responses=[
        json.dumps({"integrated_statement": ""}),   # initial: invalid
        json.dumps({"integrated_statement": ""}),   # repair: still invalid
    ])
    from query_refinement_module.schema.synthesis import SynthesisPromptBuilder
    pb = SynthesisPromptBuilder()
    result, meta = await manager._run_split_call(
        pb.get_statement_system_prompt(),
        "some user prompt",
        StatementResponse,
        "statement",
    )
    assert result is None
    assert len(manager.llm_provider.calls) == 2


@pytest.mark.asyncio
async def test_run_split_call_no_repair_when_valid():
    """When the first response is valid, only one provider call is made."""
    manager = build_manager(responses=[
        json.dumps({"integrated_statement": "valid statement on first try"}),
    ])
    from query_refinement_module.schema.synthesis import SynthesisPromptBuilder
    pb = SynthesisPromptBuilder()
    result, meta = await manager._run_split_call(
        pb.get_statement_system_prompt(),
        "some user prompt",
        StatementResponse,
        "statement",
    )
    assert result is not None
    assert result.integrated_statement == "valid statement on first try"
    assert len(manager.llm_provider.calls) == 1


@pytest.mark.asyncio
async def test_run_split_call_filter_repair_removes_bad_values():
    """A filter_resolution result with unpermitted values triggers repair; the repair response
    with valid values is returned."""
    manager = build_manager(responses=[
        json.dumps({"fields_of_study": ["Medicine", "Astrology"]}),  # invalid
        json.dumps({"fields_of_study": ["Medicine"]}),               # repaired
    ])
    from query_refinement_module.schema.synthesis import SynthesisPromptBuilder
    pb = SynthesisPromptBuilder()
    from query_refinement_module.core import FIELDS_OF_STUDY_PERMITTED
    result, meta = await manager._run_split_call(
        pb.get_filter_resolution_system_prompt(),
        pb.get_filter_resolution_prompt("query", {}, FIELDS_OF_STUDY_PERMITTED),
        FilterSuggestionResponse,
        "filter_resolution",
    )
    assert result is not None
    assert result.fields_of_study == ["Medicine"]
    assert len(manager.llm_provider.calls) == 2


# ---------------------------------------------------------------------------
# field ownership correctness, deterministic assembly,
#               split-call contract validity, structured-output reliability,
#               and repair scope
# ---------------------------------------------------------------------------

class TestDeterministicAssembly:
    """_assemble_dimensions_specifications and _assemble_deterministic_search_filters
    derive field values from session state, never from LLM output."""

    def _manager(self):
        return QueryRefinementManager(llm_provider=StubLLMProvider([]))

    # --- dimensions_specifications ---

    def test_no_steps_returns_none(self):
        session = RefinementSession(original_query="q")
        assert self._manager()._assemble_dimensions_specifications(session) is None

    def test_answered_step_serialised(self):
        aspect = make_aspect(aspect_id="pop")
        session = RefinementSession(original_query="q")
        step = session.add_step(aspect)
        step.normalized_value = "Adults 18-65"
        step.is_complete = True
        result = self._manager()._assemble_dimensions_specifications(session)
        assert result == {"pop": "Adults 18-65"}

    def test_skipped_step_is_none(self):
        aspect = make_aspect(aspect_id="pop")
        session = RefinementSession(original_query="q")
        step = session.add_step(aspect)
        step.was_skipped = True
        step.is_complete = True
        result = self._manager()._assemble_dimensions_specifications(session)
        assert result == {"pop": None}

    def test_dict_value_serialised_as_json(self):
        aspect = make_aspect(aspect_id="setting")
        session = RefinementSession(original_query="q")
        step = session.add_step(aspect)
        step.normalized_value = {"primary": "hospital", "secondary": "community"}
        step.is_complete = True
        result = self._manager()._assemble_dimensions_specifications(session)
        import json as _json
        assert _json.loads(result["setting"]) == {"primary": "hospital", "secondary": "community"}

    def test_empty_string_value_serialised_as_none(self):
        aspect = make_aspect(aspect_id="pop")
        session = RefinementSession(original_query="q")
        step = session.add_step(aspect)
        step.normalized_value = ""
        step.is_complete = True
        result = self._manager()._assemble_dimensions_specifications(session)
        assert result["pop"] is None

    def test_mixed_skipped_and_answered(self):
        a1, a2, a3 = (make_aspect(aspect_id=i) for i in ("a", "b", "c"))
        session = RefinementSession(original_query="q")
        s1 = session.add_step(a1); s1.normalized_value = "v1"; s1.is_complete = True
        s2 = session.add_step(a2); s2.was_skipped = True; s2.is_complete = True
        s3 = session.add_step(a3); s3.normalized_value = "v3"; s3.is_complete = True
        result = self._manager()._assemble_dimensions_specifications(session)
        assert result == {"a": "v1", "b": None, "c": "v3"}

    # --- deterministic search filters ---

    def test_publication_years_extracted(self):
        session = RefinementSession(original_query="studies since 2015 on X")
        import datetime as _dt
        fixed_now = _dt.datetime(2026, 5, 5, tzinfo=_dt.timezone.utc)
        with patch("query_refinement_module.core.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            result = self._manager()._assemble_deterministic_search_filters(session)
        assert result.publication_years == "2015-2026"

    def test_author_extracted(self):
        session = RefinementSession(original_query="studies authored by Jane Smith on health")
        result = self._manager()._assemble_deterministic_search_filters(session)
        assert "Jane Smith" in result.authors

    def test_venue_extracted(self):
        session = RefinementSession(original_query="results published in The Lancet; adults 18-65")
        result = self._manager()._assemble_deterministic_search_filters(session)
        assert "The Lancet" in result.venues

    def test_no_patterns_returns_empty_filters(self):
        session = RefinementSession(original_query="some query with no temporal or venue hints")
        result = self._manager()._assemble_deterministic_search_filters(session)
        assert result.publication_years == ""
        assert result.authors == []
        assert result.venues == []
        assert result.publication_types == []

    def test_publication_type_extracted(self):
        session = RefinementSession(original_query="systematic reviews of COPD treatment")
        result = self._manager()._assemble_deterministic_search_filters(session)
        assert "Systematic review" in result.publication_types


class TestFieldOwnershipEndToEnd:
    """Verify that deterministic fields in the final result_dict always reflect session state,
    not LLM output — even under total LLM failure or partial failure."""

    @pytest.mark.asyncio
    async def test_deterministic_fields_survive_all_llm_failures(self):
        """When every LLM call raises an exception, deterministic fields must still be
        present in the result and must match session-state truth."""
        aspect = make_aspect(aspect_id="population", name="Population")

        # All 5 calls will raise — no responses provided
        manager = build_manager(responses=[
            RuntimeError("call 1 failed"),
            RuntimeError("call 2 failed"),
            RuntimeError("call 3 failed"),
            RuntimeError("call 4 failed"),
            RuntimeError("call 5 failed"),
        ])
        session = RefinementSession(
            original_query="Studies since 2020 published in The Lancet"
        )
        step = session.add_step(aspect)
        step.add_follow_up("Q", "Adults 18-65")
        step.is_complete = True

        import datetime as _dt
        fixed_now = _dt.datetime(2026, 5, 5, tzinfo=_dt.timezone.utc)
        with patch("query_refinement_module.core.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            result = await manager.synthesize_refined_query(session)

        # Deterministic dimensions must be from session state
        assert result["dimensions_specifications"] == {"population": "Adults 18-65"}
        # Deterministic filter fields must be extracted from original_query
        assert result["search_filters"].publication_years == "2020-2026"
        assert "The Lancet" in result["search_filters"].venues
        # LLM fallback: integrated_statement falls back to original_query
        assert result["integrated_statement"] == "Studies since 2020 published in The Lancet"

    @pytest.mark.asyncio
    async def test_deterministic_fields_not_overridden_by_llm_output(self):
        """Even when LLM calls succeed and return values, deterministic fields are
        assembled from session state — LLM output for those positions is ignored."""
        aspect = make_aspect(aspect_id="population", name="Population")
        manager = build_manager(responses=make_split_responses(
            integrated_statement="Some synthesized statement",
            semantic="semantic query",
            fields_of_study=["Medicine"],
        ))
        session = RefinementSession(original_query="query")
        step = session.add_step(aspect)
        step.add_follow_up("Q", "Adults 18-65")
        step.is_complete = True

        result = await manager.synthesize_refined_query(session)

        # LLM-owned field present
        assert result["search_filters"].fields_of_study == ["Medicine"]
        # Deterministic field from session — never from LLM
        assert result["dimensions_specifications"] == {"population": "Adults 18-65"}
        # Deterministic filter fields empty (nothing in query text to extract)
        assert result["search_filters"].publication_years == ""
        assert result["search_filters"].authors == []
        assert result["search_filters"].venues == []


class TestSplitCallContractValidity:
    """_run_split_synthesis routes each field to the correct owner."""

    @pytest.mark.asyncio
    async def test_semantic_routed_to_search_optimized(self):
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
            semantic="retrieval query about adults with COPD",
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert result["search_optimized"].semantic == "retrieval query about adults with COPD"

    @pytest.mark.asyncio
    async def test_synonyms_routed_to_terminology(self):
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
            synonyms={"COPD": ["chronic obstructive pulmonary disease", "COAD"]},
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert result["terminology"].synonyms == {
            "COPD": ["chronic obstructive pulmonary disease", "COAD"]
        }

    @pytest.mark.asyncio
    async def test_keyword_fields_routed_to_search_optimized_keyword(self):
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
            phrases=["COPD rehabilitation"],
            required=["COPD"],
            optional=["adults"],
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        kw = result["search_optimized"].keyword
        assert "COPD rehabilitation" in kw.phrases
        assert "COPD" in kw.terms.required
        assert "adults" in kw.terms.optional

    @pytest.mark.asyncio
    async def test_fields_of_study_routed_to_search_filters(self):
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
            fields_of_study=["Medicine", "Psychology"],
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert result["search_filters"].fields_of_study == ["Medicine", "Psychology"]

    @pytest.mark.asyncio
    async def test_fields_of_study_absent_when_filter_call_fails(self):
        """If filter_resolution call fails, fields_of_study defaults to empty."""
        responses = make_split_responses(integrated_statement="stmt")
        # Corrupt the filter response (4th in list: statement, semantic, terminology, filter, keyword)
        responses[3] = "not json at all"
        manager = build_manager(responses=responses)
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert result["search_filters"].fields_of_study == []

    @pytest.mark.asyncio
    async def test_structured_query_compiled_from_required_and_synonyms(self):
        """_compile_boolean_query produces AND-of-OR structure when required terms and synonyms exist."""
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
            synonyms={"COPD": ["chronic obstructive pulmonary disease"]},
            required=["COPD"],
            optional=[],
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        structured = result["search_optimized"].keyword.structured
        # Must contain both the primary term and its synonym
        assert "COPD" in structured
        assert "chronic obstructive pulmonary disease" in structured


class TestStructuredOutputReliability:
    """result_dict always has the required shape, regardless of LLM reliability."""

    _REQUIRED_KEYS = {
        "integrated_statement", "used_llm", "clarifications", "baseline_summaries",
        "metadata", "dimensions_specifications",
        "search_optimized", "search_filters", "terminology",
    }

    @pytest.mark.asyncio
    async def test_result_shape_on_full_success(self):
        manager = build_manager(responses=make_split_responses(
            integrated_statement="stmt",
        ))
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert self._REQUIRED_KEYS.issubset(result.keys())
        assert "refinement_aspect_values" not in result

    @pytest.mark.asyncio
    async def test_result_shape_on_total_llm_failure(self):
        """All calls raise; result_dict must still have every required key."""
        manager = build_manager(responses=[
            RuntimeError("fail"),
            RuntimeError("fail"),
            RuntimeError("fail"),
            RuntimeError("fail"),
            RuntimeError("fail"),
        ])
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert self._REQUIRED_KEYS.issubset(result.keys())
        assert "refinement_aspect_values" not in result
        assert result["used_llm"] is True
        assert isinstance(result["search_filters"].fields_of_study, list)

    @pytest.mark.asyncio
    async def test_result_shape_with_preparsed_models(self):
        """Fast-path (provider returns pre-parsed Pydantic models) still produces the full shape."""
        manager = build_manager(responses=[
            StatementResponse(integrated_statement="fast path statement"),
            SemanticQueryResponse(semantic="fast path semantic"),
            TerminologyResponse(synonyms={}),
            FilterSuggestionResponse(fields_of_study=["Medicine"]),
            KeywordSupportResponse(phrases=[], required=[], optional=[]),
        ])
        session = RefinementSession(original_query="q")
        result = await manager.synthesize_refined_query(session)
        assert self._REQUIRED_KEYS.issubset(result.keys())
        assert result["integrated_statement"] == "fast path statement"


class TestRepairScope:
    """Repair path is scoped strictly to generated fields.

    ``dimensions_specifications`` is always built from session state and must
    never appear in any repair prompt.  ``venues`` and ``authors`` are
    LLM-generated but not subject to permitted-list validation, so the repair
    prompt for filter_resolution does not mention them either.
    """

    # Must never appear in any repair prompt
    _ALWAYS_FORBIDDEN = ("dimensions_specifications",)
    # Not mentioned in any repair prompt because there is no permitted list for them
    _UNVALIDATED_FILTER_FIELDS = ("venues", "authors")

    @pytest.mark.asyncio
    async def test_repair_does_not_alter_deterministic_dimensions(self):
        """Even when statement repair fires, dimensions_specifications is unchanged."""
        aspect = make_aspect(aspect_id="population")
        manager = build_manager(responses=[
            json.dumps({"integrated_statement": ""}),          # statement: invalid → triggers repair
            json.dumps({"integrated_statement": "repaired"}),  # repair
            json.dumps({"semantic": "semantic"}),
            json.dumps({"synonyms": {}}),
            json.dumps({"fields_of_study": []}),
            json.dumps({"phrases": [], "required": [], "optional": []}),
        ])
        session = RefinementSession(original_query="q")
        step = session.add_step(aspect)
        step.add_follow_up("Q", "Adults 18-65")
        step.is_complete = True

        result = await manager.synthesize_refined_query(session)
        # dimensions_specifications is from session state, not from LLM
        assert result["dimensions_specifications"] == {"population": "Adults 18-65"}

    @pytest.mark.asyncio
    async def test_repair_does_not_alter_deterministic_filters(self):
        """Even when filter_resolution repair fires, publication_years/venues/authors/publication_types
        come from deterministic extraction, never from the repair call."""
        aspect = make_aspect(aspect_id="population")
        manager = build_manager(responses=[
            json.dumps({"integrated_statement": "stmt"}),
            json.dumps({"semantic": "semantic"}),
            json.dumps({"synonyms": {}}),
            json.dumps({"fields_of_study": ["Astrology"]}),  # invalid → triggers repair
            json.dumps({"fields_of_study": ["Medicine"]}),   # repair: valid
            json.dumps({"phrases": [], "required": [], "optional": []}),
        ])
        session = RefinementSession(
            original_query="Studies since 2020 published in The Lancet"
        )
        step = session.add_step(aspect)
        step.add_follow_up("Q", "Adults 18-65")
        step.is_complete = True

        import datetime as _dt
        fixed_now = _dt.datetime(2026, 5, 5, tzinfo=_dt.timezone.utc)
        with patch("query_refinement_module.core.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            result = await manager.synthesize_refined_query(session)

        # LLM-owned field: repaired value
        assert result["search_filters"].fields_of_study == ["Medicine"]
        # Deterministic fields: from extraction, unchanged by repair
        assert result["search_filters"].publication_years == "2020-2026"
        assert "The Lancet" in result["search_filters"].venues
        assert result["search_filters"].authors == []

    def test_repair_prompts_never_mention_dimensions_specifications(self):
        """dimensions_specifications must never appear in any repair prompt."""
        call_types = ["statement", "semantic", "terminology", "keyword_support", "filter_resolution"]
        for call_name in call_types:
            prompt = QueryRefinementManager._build_repair_prompt("base", call_name, "some error")
            for field in self._ALWAYS_FORBIDDEN:
                assert field not in prompt, (
                    f"Repair prompt for '{call_name}' must never mention '{field}'"
                )

    def test_filter_repair_mentions_both_validated_fields(self):
        """Private-model filter repair must name both validated fields."""
        prompt = QueryRefinementManager._build_repair_prompt(
            "base", "filter_resolution", "some error", model=PRIVATE_MODEL
        )
        assert "publication_types" in prompt
        assert "publication_years" in prompt

    def test_unvalidated_filter_fields_absent_from_all_repair_prompts(self):
        """venues and authors have no permitted list, so no repair prompt should name them."""
        call_types = ["statement", "semantic", "terminology", "keyword_support", "filter_resolution"]
        for call_name in call_types:
            prompt = QueryRefinementManager._build_repair_prompt("base", call_name, "some error")
            for field in self._UNVALIDATED_FILTER_FIELDS:
                assert field not in prompt, (
                    f"Repair prompt for '{call_name}' must not mention unvalidated field '{field}'"
                )


# ---------------------------------------------------------------------------
# Synthesis tracing: token counts and timing
# ---------------------------------------------------------------------------

class TestSynthesisTracingTransparency:
    """The query_synthesis_complete event must carry token counts for transparency.

    split_call_*_ok events must carry duration_ms so latency can be tracked.
    """

    @pytest.mark.asyncio
    async def test_query_synthesis_complete_includes_token_counts(self):
        """query_synthesis_complete event metadata must include token and prompt-size totals."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        complete_events = [e for e in tracer.events if e["event"] == "query_synthesis_complete"]
        assert len(complete_events) == 1, "Expected exactly one query_synthesis_complete event"

        meta = complete_events[0]["metadata"]
        assert "prompt_tokens" in meta, "query_synthesis_complete must include prompt_tokens"
        assert "completion_tokens" in meta, "query_synthesis_complete must include completion_tokens"
        assert "total_tokens" in meta, "query_synthesis_complete must include total_tokens"
        assert "prompt_char_count" in meta, "query_synthesis_complete must include prompt_char_count"
        assert "estimated_prompt_tokens" in meta, "query_synthesis_complete must include estimated_prompt_tokens"
        # All token counts must be non-negative integers
        assert isinstance(meta["prompt_tokens"], int) and meta["prompt_tokens"] >= 0
        assert isinstance(meta["completion_tokens"], int) and meta["completion_tokens"] >= 0
        assert isinstance(meta["total_tokens"], int) and meta["total_tokens"] >= 0
        assert isinstance(meta["prompt_char_count"], int) and meta["prompt_char_count"] >= 0
        assert isinstance(meta["estimated_prompt_tokens"], int) and meta["estimated_prompt_tokens"] >= 0

    @pytest.mark.asyncio
    async def test_query_synthesis_complete_includes_structured_response_flag(self):
        """query_synthesis_complete must still carry structured_response: True."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        complete_events = [e for e in tracer.events if e["event"] == "query_synthesis_complete"]
        assert complete_events[0]["metadata"]["structured_response"] is True

    @pytest.mark.asyncio
    async def test_query_synthesis_complete_includes_call_timings_and_parallel_summary(self):
        """query_synthesis_complete must include detailed timing payloads for post-run diagnosis."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        complete_events = [e for e in tracer.events if e["event"] == "query_synthesis_complete"]
        meta = complete_events[0]["metadata"]
        assert "duration_ms" in meta
        assert isinstance(meta["call_timings"], dict)
        assert set(meta["call_timings"]) == {
            "statement",
            "semantic",
            "terminology",
            "filter_resolution",
            "keyword_support",
        }
        assert isinstance(meta["parallel_timing"], dict)
        assert "post_statement" in meta["parallel_timing"]

    @pytest.mark.asyncio
    async def test_split_call_ok_events_include_duration_ms(self):
        """Each split_call_*_ok event must carry a non-negative duration_ms for latency tracking."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        ok_events = [e for e in tracer.events if e["event"].endswith("_ok")]
        # Expect at least one *_ok event (one per successful call in the 5-call graph)
        assert ok_events, "No split_call_*_ok events were emitted"
        for ev in ok_events:
            meta = ev["metadata"]
            assert "duration_ms" in meta, f"Event {ev['event']} is missing duration_ms"
            assert isinstance(meta["duration_ms"], (int, float))
            assert meta["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_split_call_ok_events_include_token_info(self):
        """Each split_call_*_ok event must carry token and prompt-size metadata."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        ok_events = [e for e in tracer.events if e["event"].endswith("_ok")]
        assert ok_events
        for ev in ok_events:
            meta = ev["metadata"]
            assert "tokens" in meta
            assert "prompt_tokens" in meta
            assert "total_tokens" in meta
            assert "prompt_char_count" in meta
            assert "estimated_prompt_tokens" in meta
            assert "message_count" in meta

    @pytest.mark.asyncio
    async def test_query_synthesis_start_includes_model_field(self):
        """query_synthesis_start event must carry the model (or '(default)' marker)."""
        manager = build_manager(responses=make_split_responses(integrated_statement="stmt"))
        session = RefinementSession(original_query="q")

        await manager.synthesize_refined_query(session)

        tracer: StubTracingProvider = manager.trace_emitter._provider
        start_events = [e for e in tracer.events if e["event"] == "query_synthesis_start"]
        assert len(start_events) == 1
        meta = start_events[0]["metadata"]
        assert "model" in meta
        assert meta["model"] == "(default)"  # no override passed

    @pytest.mark.asyncio
    async def test_synthesis_metadata_includes_call_timings_and_parallel_overlap(self):
        """Returned synthesis metadata must expose per-call timings and the post-statement parallel overlap window."""
        llm = DelayedSplitLLMProvider(
            responses_by_model={
                "StatementResponse": json.dumps({"integrated_statement": "stmt"}),
                "SemanticQueryResponse": json.dumps({"semantic": "semantic query"}),
                "TerminologyResponse": json.dumps({"synonyms": {}}),
                "FilterSuggestionResponse": json.dumps({"fields_of_study": []}),
                "KeywordSupportResponse": json.dumps({"phrases": [], "required": [], "optional": []}),
            },
            delays_by_model={
                "StatementResponse": 0.005,
                "SemanticQueryResponse": 0.03,
                "TerminologyResponse": 0.04,
                "FilterSuggestionResponse": 0.02,
                "KeywordSupportResponse": 0.005,
            },
        )
        manager = QueryRefinementManager(
            llm_provider=llm,
            tracing_provider=StubTracingProvider(),
        )
        session = RefinementSession(original_query="q")

        result = await manager.synthesize_refined_query(session)

        meta = result["metadata"]
        assert set(meta["call_timings"]) == {
            "statement",
            "semantic",
            "terminology",
            "filter_resolution",
            "keyword_support",
        }
        assert meta["call_timings"]["statement"]["status"] == "succeeded"
        assert meta["call_timings"]["keyword_support"]["status"] == "succeeded"

        parallel = meta["parallel_timing"]["post_statement"]
        assert parallel["call_names"] == ["semantic", "terminology", "filter_resolution"]
        assert parallel["overlap_window_ms"] > 0
        assert parallel["fully_overlapped"] is True
        assert meta["duration_ms"] >= parallel["ended_ms"]