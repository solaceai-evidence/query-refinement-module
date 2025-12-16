from query_refinement_module.core import (
    QueryRefinementSession,
    UserCommand,
    is_user_command,
    parse_user_command,
)
from query_refinement_module.schema.model import RefinementAspect


def _make_session(aspect_id: str = "aspect_a") -> QueryRefinementSession:
    session = QueryRefinementSession(original_query="Original question")
    aspect = RefinementAspect(
        id=aspect_id,
        aspect_name="Aspect",
        aspect_description="Test aspect",
        refinement_instructions="Analyze {query}",
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
    session = QueryRefinementSession(original_query="Example query")
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


def test_parse_user_command_goto_requires_argument():
    result = parse_user_command("/goto")
    assert result.command is UserCommand.GOTO
    assert result.is_valid is False
    assert "/goto requires a step number" in result.error_message


def test_parse_user_command_goto_argument_must_be_integer():
    result = parse_user_command("/goto two")
    assert result.command is UserCommand.GOTO
    assert result.is_valid is False
    assert "must be an integer" in result.error_message


def test_handle_command_skip_marks_step_complete():
    session = _make_session()
    payload = session.handle_command(parse_user_command("/skip"))

    step = session.steps[0]
    assert payload["success"] is True
    assert step.is_complete is True
    assert step.was_skipped is True
    assert step.final_response is None


def test_handle_command_done_without_response_fails():
    session = _make_session()
    payload = session.handle_command(parse_user_command("/done"))

    assert payload["success"] is True
    assert "no additional details provided" in payload["message"].lower()
    assert session.steps[0].was_skipped is True


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


def test_handle_command_goto_invalid_step_returns_error():
    session = _make_session()
    payload = session.handle_command(parse_user_command("/goto 2"))

    assert payload["success"] is False
    assert "Invalid step number" in payload["message"]
