from query_refinement_module.core import (
    QueryRefinementSession,
    UserCommand,
    parse_user_command,
)


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


def test_parse_user_command_synthesize_is_valid():
    result = parse_user_command("/synthesize")
    assert result.command is UserCommand.SYNTHESIZE
    assert result.is_valid is True
    assert result.error_message is None


def test_synthesize_command_marks_session_for_synthesis():
    session = QueryRefinementSession(original_query="Example query")
    result = parse_user_command("/synthesize")

    payload = session.handle_command(result)

    assert payload["synthesize"] is True
    assert payload["success"] is True
    assert session.synthesis_requested is True
