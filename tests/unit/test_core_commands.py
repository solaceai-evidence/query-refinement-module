from query_refinement_module.core import (
    RefinementSession,
    UserCommand,
    is_user_command,
    parse_user_command,
)
from query_refinement_module.schema import RefinementAspect


def _make_session(aspect_id: str = "aspect_a") -> RefinementSession:
    session = RefinementSession(original_query="Original question")
    aspect = RefinementAspect(
        id=aspect_id,
        aspect_name="Aspect",
        aspect_description="Test aspect",
        evaluation_instructions="Analyze {query}",
    )
    session.add_step(aspect)
    return session


def test_parse_user_command_with_empty_slash_returns_invalid():
    result = parse_user_command("/")
    assert result.command is UserCommand.NONE
    assert result.is_valid is False
    assert result.error_message == "Empty command. Type /help for available commands."


def test_parse_user_command_with_whitespace_after_slash_returns_invalid():
    result = parse_user_command("/   ")
    assert result.command is UserCommand.NONE
    assert result.is_valid is False
    assert result.error_message == "Empty command. Type /help for available commands."


def test_parse_user_command_with_known_command_remains_valid():
    result = parse_user_command("/help")
    assert result.command is UserCommand.HELP
    assert result.is_valid is True
    assert result.error_message is None


def test_parse_user_command_submit_is_valid():
    result = parse_user_command("/submit")
    assert result.command is UserCommand.SUBMIT
    assert result.is_valid is True
    assert result.error_message is None


def test_submit_command_marks_session_for_synthesis():
    session = RefinementSession(original_query="Example query")
    result = parse_user_command("/submit")

    payload = session.handle_command(result)

    assert payload["submit"] is True
    assert payload["success"] is True
    assert session.synthesis_requested is True


def test_is_user_command_detects_leading_slash():
    assert is_user_command("/status") is True
    assert is_user_command(" /status") is True


def test_is_user_command_returns_false_for_regular_input():
    assert is_user_command("status") is False
    assert is_user_command("") is False


def test_parse_user_command_unknown_returns_error():
    result = parse_user_command("/unknown")
    assert result.is_valid is False
    assert result.error_message.startswith("Unknown command")


def test_parse_user_command_unknown_with_argument_returns_error():
    result = parse_user_command("/unknown extra text")
    assert result.is_valid is False
    assert result.error_message.startswith("Unknown command")


def test_parse_user_command_clear_is_valid():
    result = parse_user_command("/clear")
    assert result.command is UserCommand.CLEAR
    assert result.is_valid is True
    assert result.error_message is None


def test_handle_command_skip_marks_step_complete():
    session = _make_session()
    payload = session.handle_command(parse_user_command("/skip"))

    step = session.steps[0]
    assert payload["success"] is True
    assert step.is_complete is True
    assert step.was_skipped is True
    assert step.normalized_value_as_str is None


def test_handle_command_done_without_response_fails():
    """Test that /done without a response marks as complete (v2.0 behavior)."""
    session = _make_session()
    payload = session.handle_command(parse_user_command("/done"))

    assert payload["success"] is True
    assert "no additional details provided" in payload["message"].lower()
    # In v2.0, /done without response marks as complete but not skipped
    assert session.steps[0].is_complete is True


def test_handle_command_done_with_response_marks_complete():
    session = _make_session()
    step = session.steps[0]
    step.add_follow_up(question="Q?", response="Answer")

    payload = session.handle_command(parse_user_command("/done"))

    assert payload["success"] is True
    assert step.is_complete is True
    assert step.needs_review is False
    assert step.was_skipped is False


def test_handle_command_status_returns_summary():
    session = _make_session()
    payload = session.handle_command(parse_user_command("/status"))

    assert payload["success"] is True
    assert "Session Status" in payload["message"]


def test_handle_command_clear_clears_current_aspect():
    """Test /clear clears current aspect data and flags for regeneration."""
    session = _make_session()
    step = session.steps[0]
    step.add_follow_up(question="Q?", response="Answer")
    step.normalized_value = "some value"
    
    payload = session.handle_command(parse_user_command("/clear"))
    
    assert payload["success"] is True
    assert payload["regenerate_question"] is True
    assert len(step.conversation_history) == 0
    assert step.normalized_value is None
    assert step.is_complete is False


def test_handle_command_back_truncates_steps():
    """Test /back removes current and future steps in sequential mode."""
    session = RefinementSession(original_query="Test query")
    
    # Add 3 steps
    for i in range(3):
        aspect = RefinementAspect(
            id=f"aspect_{i}",
            aspect_name=f"Aspect {i}",
            aspect_description=f"Test aspect {i}",
            evaluation_instructions="Analyze {query}",
        )
        session.add_step(aspect)
    
    # Complete first step, make second active
    session.steps[0].is_complete = True
    
    # Go back should remove step 1 (current) and step 2 (future)
    payload = session.handle_command(parse_user_command("/back"))
    
    assert payload["success"] is True
    assert len(session.steps) == 1  # Only first step remains
    assert "cleared" in payload["message"].lower()


def test_handle_command_skip_clears_all_data():
    """Test /skip clears follow-up history and refinement_aspect_value."""
    session = _make_session()
    step = session.steps[0]
    step.add_follow_up(question="Q1?", response="Answer 1")
    step.add_follow_up(question="Q2?", response="Answer 2")
    step.normalized_value = "extracted value"
    
    payload = session.handle_command(parse_user_command("/skip"))
    
    assert payload["success"] is True
    assert step.is_complete is True
    assert step.was_skipped is True
    assert step.normalized_value is None
    assert len(step.conversation_history) == 0  # All history cleared


def test_handle_command_restart_truncates_all_steps():
    """Test /restart clears all steps for full regeneration."""
    session = RefinementSession(original_query="Test query")
    
    # Add and complete multiple steps
    for i in range(3):
        aspect = RefinementAspect(
            id=f"aspect_{i}",
            aspect_name=f"Aspect {i}",
            aspect_description=f"Test aspect {i}",
            evaluation_instructions="Analyze {query}",
        )
        session.add_step(aspect)
        session.steps[i].is_complete = True
    
    payload = session.handle_command(parse_user_command("/restart"))
    
    assert payload["success"] is True
    assert len(session.steps) == 0  # All steps cleared
    assert session.synthesis_requested is False
