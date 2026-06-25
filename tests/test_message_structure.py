"""
Test message structure for dimension refinement prompts.

Verifies:
1. Message ordering: global → completed_dims → current_dim → query → history
2. Cache marker applied to global directive only
3. Terminal reinforcement fires at threshold
"""

import pytest
import importlib
from query_refinement_module.session_models import AspectRefinementState
from query_refinement_module.schema.models import RefinementDimension
from query_refinement_module.schema import registry
import query_refinement_module.schema.templates as templates_module
import query_refinement_module.schema.prompt_builder as prompt_builder_module


def _load_framework_from_current_yaml():
    import os
    os.environ["REFINEMENT_FRAMEWORK_PATH"] = "refinement_frameworks/frameworks.yaml"
    registry.reload_from_env()
    framework_names = registry.list_frameworks()
    assert framework_names, "Should load at least one framework"
    aspects = registry.get_framework(framework_names[0])
    assert aspects is not None, "Should load framework aspects"
    assert len(aspects) > 0, "Should have aspects"
    return aspects


def test_message_structure_basic():
    """Test baseline message structure: global directive, dimension spec, user query."""
    aspects = _load_framework_from_current_yaml()
    aspect = aspects[0]

    state = AspectRefinementState(refinement_aspect=aspect)
    query = "Test query about intervention effectiveness"
    messages = state.get_messages(query=query)

    # 1. First message: Global directive with cache marker
    assert messages[0]["role"] == "system"
    assert "Research Query Refinement" in messages[0]["content"] or "System Directive" in messages[0]["content"]
    assert messages[0].get("_cache") is True

    # 2. Dimension specification present somewhere
    dimension_msg = next(
        (m for m in messages[1:] if m["role"] == "system" and aspect.name in m["content"]),
        None,
    )
    assert dimension_msg is not None, "Should contain current dimension specification"
    assert aspect.description in dimension_msg["content"]

    # 3. User query present
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs, "Should contain a user query message"
    assert query in user_msgs[-1]["content"]


def test_message_structure_with_dependencies():
    """Test that completed dimensions and dependencies are included correctly."""
    aspects = _load_framework_from_current_yaml()

    aspects_with_deps = [a for a in aspects if a.depends_on]
    if not aspects_with_deps:
        pytest.skip("No aspects with dependencies in framework")

    aspect = aspects_with_deps[0]
    state = AspectRefinementState(refinement_aspect=aspect)

    dependency_context = {}
    for dep_id in aspect.depends_on:
        dependency_context[dep_id] = {
            "name": dep_id.replace("_", " ").title(),
            "description": f"Description of {dep_id}",
            "value": f"Clarified value for {dep_id}"
        }

    messages = state.get_messages(query="Test query", dependency_context=dependency_context)

    dep_msg = None
    for msg in messages:
        if msg["role"] == "system":
            if all(dependency_context[dep_id]["value"] in msg["content"] for dep_id in aspect.depends_on):
                dep_msg = msg
                break

    assert dep_msg is not None, f"Should include dependency values. Aspect depends on: {aspect.depends_on}"
    for dep_id in aspect.depends_on:
        assert dependency_context[dep_id]["value"] in dep_msg["content"]


def test_message_structure_with_conversation_history():
    """Test that conversation history is appended correctly."""
    aspects = _load_framework_from_current_yaml()
    aspect = aspects[0]
    state = AspectRefinementState(refinement_aspect=aspect)

    state.add_follow_up(
        question="Can you clarify the population?",
        response="Adults aged 18-65 with diabetes"
    )
    state.add_follow_up(
        question="What about exclusion criteria?",
        response="Exclude pregnant women and children"
    )

    query = "Test query"
    messages = state.get_messages(query=query)

    user_query_idx = next(
        (i for i, m in enumerate(messages) if m["role"] == "user" and query in m["content"]),
        None,
    )
    assert user_query_idx is not None, "Should find user query"

    conv_messages = messages[user_query_idx + 1:]
    assert len(conv_messages) >= 4, "Should have at least 4 messages (2 Q&A pairs)"

    assert conv_messages[0]["role"] == "assistant"
    assert "clarify the population" in conv_messages[0]["content"].lower()

    assert conv_messages[1]["role"] == "user"
    assert "Adults aged 18-65" in conv_messages[1]["content"]

    assert conv_messages[2]["role"] == "assistant"
    assert "exclusion criteria" in conv_messages[2]["content"].lower()

    assert conv_messages[3]["role"] == "user"
    assert "pregnant women" in conv_messages[3]["content"]


def test_only_global_directive_is_cached():
    """Test that _cache marker is applied only to the global directive."""
    aspects = _load_framework_from_current_yaml()
    aspect = aspects[0]
    state = AspectRefinementState(refinement_aspect=aspect)

    messages = state.get_messages(query="Test query")

    cache_marked = [msg for msg in messages if msg.get("_cache") is True]
    assert len(cache_marked) == 1, "Only the global directive should be marked for caching"
    assert cache_marked[0] == messages[0]

    for msg in messages[1:]:
        assert msg.get("_cache") is not True, "Only global directive should be cached"


def _build_plain_dimension():
    return RefinementDimension(
        id="population",
        name="Population",
        description="Target population",
        specifications="Extract the population first, then ask only for what is missing.",
    )


def _reload_prompt_modules(monkeypatch, *, prompt_variant=None, llm_model=None):
    if prompt_variant is None:
        monkeypatch.delenv("PROMPT_VARIANT", raising=False)
    else:
        monkeypatch.setenv("PROMPT_VARIANT", prompt_variant)

    if llm_model is None:
        monkeypatch.delenv("LLM_MODEL", raising=False)
    else:
        monkeypatch.setenv("LLM_MODEL", llm_model)

    importlib.reload(templates_module)
    return importlib.reload(prompt_builder_module)


def test_open_llm_completed_context_reminder_preserves_question_gating(monkeypatch):
    prompt_builder = _reload_prompt_modules(
        monkeypatch,
        prompt_variant="open_llm",
        llm_model="ollama/qwen2.5:72b",
    )
    builder = prompt_builder.PromptBuilder()
    dimension = _build_plain_dimension()
    dimension.depends_on = ["condition"]

    messages = builder.build_refinement_messages(
        dimension=dimension,
        query="population effects of heat exposure",
        conversation_history=[],
        completed_context=[
            {
                "id": "condition",
                "name": "Condition",
                "description": "Target condition",
                "value": "heat stroke",
                "was_skipped": False,
            }
        ],
        terminal_reinforcement_threshold=3,
    )

    assert "omit" in messages[-1]["content"].lower()
    assert "trigger" in messages[-1]["content"].lower()
    assert "fragment relevant to the current dimension" in messages[-1]["content"].lower()


def test_terminal_reinforcement_does_not_include_user_context(monkeypatch):
    """Terminal reinforcement should contain global directive + dimension spec only."""
    prompt_builder = _reload_prompt_modules(monkeypatch)
    builder = prompt_builder.PromptBuilder()
    dimension = _build_plain_dimension()

    messages = builder.build_refinement_messages(
        dimension=dimension,
        query="population effects of heat exposure",
        conversation_history=[
            {"question": "Q1?", "response": "A1"},
            {"question": "Q2?", "response": "A2"},
            {"question": "Q3?", "response": "A3"},
        ],
        terminal_reinforcement_threshold=3,
    )

    assert "USER CONTEXT" not in messages[-1]["content"]
    assert "Style cue" not in messages[-1]["content"]
    assert "INTERACTION STYLE" in messages[-1]["content"] or "Research Query Refinement" in messages[-1]["content"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
