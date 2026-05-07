"""
Test message structure matches YAML schema with proper caching.

Verifies:
1. Message ordering: global → user_context → completed_dims → current_dim → query → history
2. Cache markers applied to global directive and user context
3. User context included when specified in framework
"""

import pytest
from query_refinement_module.session_models import AspectRefinementState
from query_refinement_module.schema.models import RefinementDimension, UserContext
from query_refinement_module.schema import registry


def test_message_structure_with_user_context():
    """Test that messages include user context after global directive with cache markers."""
    # Load framework with user context (force reload from specific file)
    import os
    os.environ["REFINEMENT_FRAMEWORK_PATH"] = "refinement_frameworks/frameworks.yaml"
    registry.reload_from_env()
    
    aspects = registry.get_framework("pico_advanced")
    assert aspects is not None, "Should load PICO framework"
    assert len(aspects) > 0, "Should have aspects"
    
    # Get first aspect with user context
    aspect = aspects[0]
    assert aspect.user_context is not None, "Aspect should have user context from framework"
    
    # Create refinement state
    state = AspectRefinementState(refinement_aspect=aspect)
    
    # Build messages
    query = "Test query about intervention effectiveness"
    messages = state.get_messages(query=query)
    
    # Verify structure
    assert len(messages) >= 4, "Should have at least 4 messages: global, user_context, dimension, query"
    
    # 1. First message: Global directive with cache marker
    assert messages[0]["role"] == "system", "First message should be system (global directive)"
    assert "Research Query Refinement" in messages[0]["content"] or "System Directive" in messages[0]["content"], "Should contain global instructions"
    assert messages[0].get("_cache") is True, "Global directive should be marked for caching"
    
    # 2. Second message: User context with cache marker
    assert messages[1]["role"] == "system", "Second message should be system (user context)"
    assert any(kw in messages[1]["content"].lower() for kw in ["user", "context", "tone", "complexity"]), \
        "Should contain user context information"
    assert messages[1].get("_cache") is True, "User context should be marked for caching"
    
    # 3. Find dimension specification
    dimension_msg = None
    for msg in messages[2:]:
        if msg["role"] == "system" and aspect.name in msg["content"]:
            dimension_msg = msg
            break
    assert dimension_msg is not None, "Should contain current dimension specification"
    assert aspect.description in dimension_msg["content"], "Should include dimension description"
    
    # 4. A user message containing the query must be present.
    # Note: a style-cue system message may appear after the user query (recency-bias
    # counter for open-weight models), so we search rather than checking messages[-1].
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs, "Should contain a user query message"
    assert query in user_msgs[-1]["content"], "Should contain original query"


def test_message_structure_with_dependencies():
    """Test that completed dimensions and dependencies are included correctly."""
    # Load framework
    import os
    os.environ["REFINEMENT_FRAMEWORK_PATH"] = "refinement_frameworks/frameworks.yaml"
    registry.reload_from_env()
    
    aspects = registry.get_framework("pico_advanced")
    
    # Get an aspect that has dependencies (e.g., outcome might depend on intervention)
    aspects_with_deps = [a for a in aspects if a.depends_on]
    
    if not aspects_with_deps:
        pytest.skip("No aspects with dependencies in framework")
    
    aspect = aspects_with_deps[0]
    state = AspectRefinementState(refinement_aspect=aspect)
    
    # Create dependency context
    dependency_context = {}
    for dep_id in aspect.depends_on:
        dependency_context[dep_id] = {
            "name": dep_id.replace("_", " ").title(),
            "description": f"Description of {dep_id}",
            "value": f"Clarified value for {dep_id}"
        }
    
    # Build messages with dependencies
    query = "Test query"
    messages = state.get_messages(query=query, dependency_context=dependency_context)
    
    # Find dependency message (completed dimensions that serve as dependencies)
    dep_msg = None
    for msg in messages:
        # Look for system message containing dependency values
        if msg["role"] == "system":
            # Check if it contains the actual dependency values (not just mentions in global directive)
            has_all_values = all(
                dependency_context[dep_id]["value"] in msg["content"]
                for dep_id in aspect.depends_on
            )
            if has_all_values:
                dep_msg = msg
                break
    
    assert dep_msg is not None, f"Should include previously clarified dimensions with dependency values. Aspect depends on: {aspect.depends_on}"
    
    # Verify all dependency values are included
    for dep_id in aspect.depends_on:
        expected_value = dependency_context[dep_id]["value"]
        assert expected_value in dep_msg["content"], f"Should include dependency value for {dep_id}"


def test_message_structure_with_conversation_history():
    """Test that conversation history is appended correctly."""
    # Load framework
    import os
    os.environ["REFINEMENT_FRAMEWORK_PATH"] = "refinement_frameworks/frameworks.yaml"
    registry.reload_from_env()
    
    aspects = registry.get_framework("pico_advanced")
    aspect = aspects[0]
    state = AspectRefinementState(refinement_aspect=aspect)
    
    # Add conversation history
    state.add_follow_up(
        question="Can you clarify the population?",
        response="Adults aged 18-65 with diabetes"
    )
    state.add_follow_up(
        question="What about exclusion criteria?",
        response="Exclude pregnant women and children"
    )
    
    # Build messages
    query = "Test query"
    messages = state.get_messages(query=query)
    
    # Find conversation messages (after user query)
    user_query_idx = None
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and query in msg["content"]:
            user_query_idx = i
            break
    
    assert user_query_idx is not None, "Should find user query"
    
    # Conversation history should follow
    conv_messages = messages[user_query_idx + 1:]
    
    assert len(conv_messages) >= 4, "Should have at least 4 messages (2 Q&A pairs)"
    
    # Verify alternating pattern: assistant (question), user (response)
    assert conv_messages[0]["role"] == "assistant", "First follow-up should be assistant question"
    assert "clarify the population" in conv_messages[0]["content"].lower()
    
    assert conv_messages[1]["role"] == "user", "Second follow-up should be user response"
    assert "Adults aged 18-65" in conv_messages[1]["content"]
    
    assert conv_messages[2]["role"] == "assistant", "Third follow-up should be assistant question"
    assert "exclusion criteria" in conv_messages[2]["content"].lower()
    
    assert conv_messages[3]["role"] == "user", "Fourth follow-up should be user response"
    assert "pregnant women" in conv_messages[3]["content"]


def test_no_user_context_when_not_specified():
    """Test that user context is not included when framework doesn't specify it."""
    # Create a dimension without user context
    dimension = RefinementDimension(
        id="test_dim",
        name="Test Dimension",
        description="Test dimension without user context",
        specifications="Evaluate something",
        allow_follow_up=True,
        max_follow_ups=3
    )
    
    state = AspectRefinementState(refinement_aspect=dimension)
    
    # Build messages
    query = "Test query"
    messages = state.get_messages(query=query)
    
    # Should have: global, dimension, query (no user context)
    assert len(messages) == 3, "Should have 3 messages when no user context"
    
    # First should still be global with cache
    assert messages[0]["role"] == "system"
    assert messages[0].get("_cache") is True
    
    # Second should be dimension (not user context)
    assert messages[1]["role"] == "system"
    assert dimension.name in messages[1]["content"]
    
    # Third should be query
    assert messages[2]["role"] == "user"
    assert query in messages[2]["content"]


def test_cache_markers_only_on_first_two_system_messages():
    """Test that _cache markers are only applied to global and user context."""
    # Load framework with user context
    import os
    os.environ["REFINEMENT_FRAMEWORK_PATH"] = "refinement_frameworks/frameworks.yaml"
    registry.reload_from_env()
    
    aspects = registry.get_framework("pico_advanced")
    aspect = aspects[0]
    state = AspectRefinementState(refinement_aspect=aspect)
    
    # Build messages
    messages = state.get_messages(query="Test query")
    
    # Check cache markers
    cache_marked = [msg for msg in messages if msg.get("_cache") is True]
    
    # Should have exactly 2 cached messages (global + user_context)
    assert len(cache_marked) == 2, "Should have exactly 2 messages marked for caching"
    assert cache_marked[0] == messages[0], "First cached message should be global directive"
    assert cache_marked[1] == messages[1], "Second cached message should be user context"
    
    # All other system messages should NOT be cached
    for msg in messages[2:]:
        if msg["role"] == "system":
            assert msg.get("_cache") is not True, "Dimension/dependency messages should not be cached"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
