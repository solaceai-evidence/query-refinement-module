# User Control Commands

The query refinement module supports user control commands to navigate and manage refinement sessions. Commands are prefixed with `/` to distinguish them from regular responses.

## Available Commands

### Navigation Commands

Navigate between refinement steps:

- **`/back`** or **`/prev`**: Go back to the previous step
- **`/goto <number>`**: Jump to a specific step (1-indexed)
- **`/restart`**: Restart the entire refinement session

### Control Commands

Control the refinement flow:

- **`/skip`**: Skip the current dimension without providing a value
- **`/done`**: Mark current step complete with the last response as final value (stops follow-up questions)
- **`/continue`**: Continue with the current refinement (no-op, for explicit continuation)
- **`/finish`**: Alias for `/done`

### Information Commands

Query session status:

- **`/status`**: Show current session progress
- **`/steps`**: List all refinement steps with completion status
- **`/help`**: Display help message with all commands

## Usage Example

```python
from core import (
    RefinementSession,
    is_user_command,
    parse_user_command,
)

# In your refinement loop
user_input = get_user_input()

if is_user_command(user_input):
    # Parse and execute command
    cmd_result = parse_user_command(user_input)
    result = session.handle_command(cmd_result)
    
    if result['success']:
        print(result['message'])
        
        # Handle navigation commands
        if cmd_result.command in [UserCommand.BACK, UserCommand.GOTO, UserCommand.RESTART]:
            # Active step has changed, continue loop
            continue
            
        # Handle control commands
        elif cmd_result.command in [UserCommand.SKIP, UserCommand.DONE]:
            # Current step completed, move to next
            continue
    else:
        print(f"Error: {result['message']}")
else:
    # Process as normal answer
    active_step.user_response = user_input
    # ... continue with refinement logic
```

## Command Parsing

### `is_user_command(user_input: str) -> bool`

Detects if input is a command (starts with `/`).

```python
is_user_command("/help")      # True
is_user_command("my answer")  # False
```

### `parse_user_command(user_input: str) -> CommandResult`

Parses a command string and validates it.

Returns a `CommandResult` with:
- `command`: The `UserCommand` enum value
- `argument`: Optional argument (e.g., step number for `/goto`)
- `is_valid`: Whether the command is valid
- `error_message`: Error description if invalid

```python
result = parse_user_command("/goto 2")
# result.command = UserCommand.GOTO
# result.argument = "2"
# result.is_valid = True

result = parse_user_command("/goto")
# result.is_valid = False
# result.error_message = "/goto requires a step number..."
```

## Session Command Handling

### `session.handle_command(cmd_result: CommandResult) -> Dict[str, Any]`

Executes a parsed command and returns result dictionary:

```python
{
    "success": True,           # Whether command succeeded
    "message": "...",          # Human-readable result message
    # Additional command-specific data
}
```

### Navigation Behavior

#### `/back` or `/prev`
- Returns to the previous step
- Marks current step as incomplete
- Clears current step's response and final value
- Reactivates previous step

```python
result = session.handle_command(parse_user_command("/back"))
# result['step'] contains the previous step
# result['step_index'] contains the new index
```

#### `/goto <number>`
- Jumps to specific step (1-indexed)
- Marks target step and all following steps as incomplete
- Validates step number is in valid range

```python
result = session.handle_command(parse_user_command("/goto 3"))
# Jumps to step 3, marks steps 3, 4, ... as incomplete
```

#### `/restart`
- Resets all steps to incomplete
- Clears all responses and final values
- Resets follow-up counts
- Restores `current_query` to `original_query`
- Clears conversation history

### Control Behavior

#### `/skip`
- Marks current step as complete
- Sets `final_value` to `None` (explicitly skipped)
- Moves to next step

```python
result = session.handle_command(parse_user_command("/skip"))
# Current dimension is skipped, no value set
```

#### `/done` or `/finish`
- Marks current step as complete
- Sets `final_value` to `user_response`
- Stops any follow-up questions for this dimension
- Requires at least one response to be provided

```python
active_step.user_response = "Adults 18-65"
result = session.handle_command(parse_user_command("/done"))
# Step completed with "Adults 18-65" as final value
```

### Information Behavior

#### `/status`
Returns session progress:
- Total steps and completion count
- Total follow-up questions asked
- Current active step

```python
result = session.handle_command(parse_user_command("/status"))
# result['message'] contains formatted status
# result['summary'] contains detailed statistics
# result['active_step'] contains current RefinementStep
```

#### `/steps`
Lists all steps with visual indicators:
- `✓` = completed
- `→` = active
- `○` = not started

Also shows follow-up count for each step.

```python
result = session.handle_command(parse_user_command("/steps"))
# result['message'] contains formatted list
# result['steps'] contains all RefinementStep objects
```

#### `/help`
Returns formatted help text with all commands and examples.

## Integration Pattern

Here's a complete integration pattern for a refinement loop:

```python
def run_refinement_session(session: RefinementSession, llm_provider):
    """Run an interactive refinement session with command support."""
    
    while not session.is_complete():
        active_step = session.get_active_step()
        if not active_step:
            break
        
        # Generate question if needed
        if not active_step.user_response:
            system_prompt, user_prompt = active_step.get_prompts(session.current_query)
            question = llm_provider.generate(system_prompt, user_prompt)
            print(f"\nAssistant: {question}")
        
        # Get user input
        user_input = input("You: ").strip()
        
        # Handle commands
        if is_user_command(user_input):
            cmd_result = parse_user_command(user_input)
            result = session.handle_command(cmd_result)
            
            print(result['message'])
            
            if not result['success']:
                continue  # Try again on error
            
            # Navigation: loop continues with new active step
            if cmd_result.command in [UserCommand.BACK, UserCommand.GOTO, UserCommand.RESTART]:
                continue
            
            # Skip/Done: current step complete, move to next
            if cmd_result.command in [UserCommand.SKIP, UserCommand.DONE]:
                continue
            
            # Info commands: show and continue
            if cmd_result.command in [UserCommand.STATUS, UserCommand.STEPS, UserCommand.HELP]:
                continue
        
        else:
            # Process regular answer
            active_step.user_response = user_input
            
            # Check if follow-up needed
            if active_step.can_ask_followup():
                # Generate follow-up question
                followup = generate_followup(active_step, user_input)
                active_step.add_followup(followup, user_input)
                print(f"\nFollow-up: {followup}")
            else:
                # Mark complete
                active_step.complete_with_value(user_input)
    
    print("\n✓ Refinement complete!")
    return session
```

## Error Handling

Commands are validated before execution:

```python
result = parse_user_command("/goto")
if not result.is_valid:
    print(result.error_message)
    # Output: "/goto requires a step number. Example: /goto 2"

result = parse_user_command("/goto 99")
handle_result = session.handle_command(result)
if not handle_result['success']:
    print(handle_result['message'])
    # Output: "Invalid step number. Valid range: 1-3"
```

## Design Principles

1. **Domain-Agnostic**: Commands work with any refinement schema
2. **Safe Navigation**: Invalid jumps are rejected with clear errors
3. **State Preservation**: Navigation maintains consistency
4. **Clear Feedback**: All commands return human-readable messages
5. **Flexible Flow**: Users control pacing and direction

## Testing

See `examples/test_user_commands.py` for comprehensive examples of:
- Command parsing and validation
- Navigation scenarios
- Control flow management
- Information queries
- Full refinement simulation
