# User Control Commands

Refinement sessions accept slash-prefixed commands to manage navigation, control flow, and progress reporting. All parsing lives in `query_refinement_module.core`, so the same behavior is available from the CLI, API service, and custom integrations.

## 1. Command Reference

| Command | Aliases | Purpose |
| --- | --- | --- |
| `/back` | `/prev` | Return to the previous step and invalidate subsequent dependents |
| `/goto <n>` | — | Jump to step `n` (1-indexed) and reopen that branch |
| `/restart` | — | Reset the session to its initial state |
| `/skip` | — | Mark the current step complete without asking more questions |
| `/done` | — | Commit the current step with whatever information has been collected |
| `/submit` | `/end` | Request early termination and move straight to synthesis |
| `/status` | — | Print a progress summary with completion counts |
| `/steps` | — | List every aspect with status icons and follow-up counts |
| `/help` | — | Return formatted help text covering all commands |

All commands start with `/`. Anything else is treated as a normal answer.

## 2. Parsing Utilities

```python
from query_refinement_module.core import is_user_command, parse_user_command

is_user_command("/help")   # True
is_user_command("Adults")  # False

result = parse_user_command("/goto 2")
assert result.command.value == "goto"
assert result.argument == "2"
assert result.is_valid
```

`parse_user_command` returns a `CommandResult` dataclass with four fields:

- `command` (`UserCommand` enum)
- `argument` (`Optional[str]`)
- `is_valid` (`bool`)
- `error_message` (`Optional[str]`)

If parsing fails, `command` is set to `UserCommand.NONE`, `is_valid` is `False`, and `error_message` describes the issue.

## 3. Applying Commands to a Session

```python
from query_refinement_module.core import QueryRefinementSession

session = QueryRefinementSession(original_query="...")
# session.steps populated elsewhere

cmd_result = parse_user_command("/skip")
response = session.handle_command(cmd_result)

if response["success"]:
    print(response["message"])
else:
    print(f"Command failed: {response['message']}")
```

`QueryRefinementSession.handle_command` always returns a dictionary with at least:

- `success`: `True`/`False`
- `message`: human-readable feedback

Some commands add more detail (for example, `/status` includes a `summary` payload, `/steps` returns the list of step descriptors, and `/submit` flags `"submit": True`).

## 4. Command Behaviour Highlights

### Navigation

- `/back` and `/prev` reopen the last completed/active step, clear its in-progress answer, and call `_invalidate_dependents` so every dependent aspect is marked `needs_review=True`.
- `/goto <n>` jumps to step `n`. The target and all later steps become incomplete without erasing their conversation history, ensuring revised answers cannot rely on stale dependency context.
- `/restart` resets the entire session: steps become incomplete, follow-up counts reset, and conversation history is cleared.

### Flow Control

- `/skip` and `/done` are operational synonyms: each marks the current step complete while preserving the existing conversation history. If no clarification was captured, the step is recorded as intentionally skipped so dependent aspects can continue without re-prompting for the same detail.
- `/submit` (and its alias `/end`) sets `session.synthesis_requested = True` so call sites can break out of the refinement loop and proceed directly to query synthesis.

### Information

- `/status` wraps `QueryRefinementSession.get_step_summary()`, returning totals for completed steps, steps needing review, active follow-up counts, and the current step name.
- `/steps` prints each step with a textual status (`completed`, `needs review`, `active`, `not started`) and the current follow-up count.
- `/help` pulls from `query_refinement_module.core.get_help_text()` to display up-to-date instructions and examples.

## 5. Loop Integration Template

```python
from query_refinement_module.core import (
    QueryRefinementSession,
    is_user_command,
    parse_user_command,
    UserCommand,
)

def run_loop(session: QueryRefinementSession, ask_llm):
    while not session.is_complete() and not session.synthesis_requested:
        step = session.get_active_step()
        if not step:
            break

        question_text = step.analysis_suggested_question or ""

        # Ask the model for the next question when needed
        if not step.follow_up_history:
            system_prompt, user_prompt = step.get_prompts(session.original_query)
            question_text = ask_llm(system_prompt, user_prompt)
            print(f"Assistant: {question_text}")

        user_input = input("You: ").strip()

        if is_user_command(user_input):
            cmd = parse_user_command(user_input)
            if not cmd.is_valid:
                print(cmd.error_message)
                continue

            result = session.handle_command(cmd)
            print(result["message"])

            if not result["success"]:
                continue

            if cmd.command in {UserCommand.BACK, UserCommand.GOTO, UserCommand.RESTART}:
                continue  # active step changed

            if cmd.command in {UserCommand.SKIP, UserCommand.DONE}:
                continue  # move forward automatically

            if result.get("submit"):
                break

            continue  # info commands fall through to next loop iteration

        # Regular answer path
        step.add_follow_up(question=question_text, response=user_input)

        if not step.can_ask_followup():
            step.is_complete = True
            step.needs_review = False

    return session

For follow-up rounds you can call `step.format_follow_up_prompt_template(session.original_query)` to build a dedicated prompt that includes conversation history and dependency context before generating the next question.
```

## 6. Error Handling Patterns

- `parse_user_command` protects against malformed inputs (missing arguments, unknown commands, non-integer `/goto` targets). Always check `CommandResult.is_valid` before invoking `handle_command`.
- `handle_command` returns a descriptive message for domain errors (for example, `/back` on the first step, or `/goto 99` when only three steps exist). Display these messages verbatim—they are written for end users.

## 7. Test Coverage

Automated tests in `tests/test_core_commands.py` and `tests/test_manager.py` cover:

- Parsing edge cases and alias handling
- Navigation effects (including dependency invalidation)
- Skip/done flows and follow-up termination
- Status and help payloads
- `/submit` semantics inside the manager pipeline

Use these tests as templates when extending command behaviour or introducing new workflows.
