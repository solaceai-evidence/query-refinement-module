 
from query_refinement_module.core import (
    QueryAspectRefiner,
    QueryRefinementSession,
    QueryRefinementManager,
    CommandResult,
    UserCommand,
)
from tests.unit.test_helpers import make_aspect

def test_followup_null_and_empty_history():
    aspect = make_aspect(allow_follow_up=True)
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    assert refiner.follow_up_count == 0
    assert refiner.refinement_aspect_value_as_str is None
    assert refiner.get_conversation_history_text() == "no previous follow-up questions."
    prompt = refiner.format_follow_up_prompt_template("query")
    assert "FOLLOW-UP CONTEXT" in prompt
    assert "no previous follow-up questions." in prompt


def test_followup_max_rounds():
    aspect = make_aspect(allow_follow_up=True, max_follow_ups=2)
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    refiner.add_follow_up("Q1", "A1")
    refiner.add_follow_up("Q2", "A2")
    assert not refiner.can_ask_followup()


def test_followup_with_null_response():
    aspect = make_aspect(allow_follow_up=True)
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    refiner.add_follow_up("Q1", None)
    assert refiner.refinement_aspect_value_as_str is None


def test_followup_manager_edge_cases():
    aspect = make_aspect(allow_follow_up=True)
    manager = QueryRefinementManager(llm_provider=None, query_analyzer=None)
    session = QueryRefinementSession(original_query="query")
    step = session.add_step(aspect)
    step.is_complete = True
    result = manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert result["rounds"] == 0


def test_user_command_edge_cases():
    session = QueryRefinementSession(original_query="query")
    aspect = make_aspect()
    session.add_step(aspect)
    # /back at first step
    result = session.handle_command(CommandResult(command=UserCommand.BACK, is_valid=True))
    assert not result["success"]
    # /goto invalid step
    result = session.handle_command(CommandResult(command=UserCommand.GOTO, argument="99", is_valid=True))
    assert not result["success"]
    # /skip with no active step
    session.steps[0].is_complete = True
    result = session.handle_command(CommandResult(command=UserCommand.SKIP, is_valid=True))
    assert not result["success"]
    # /done with no active step
    result = session.handle_command(CommandResult(command=UserCommand.DONE, is_valid=True))
    assert not result["success"]
    # /restart clears all
    session.steps[0].is_complete = False
    session.steps[0].follow_up_history = [{"question": "Q", "response": "A"}]
    result = session.handle_command(CommandResult(command=UserCommand.RESTART, is_valid=True))
    assert result["success"]
    assert session.steps[0].follow_up_history == []
