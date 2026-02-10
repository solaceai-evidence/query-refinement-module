# Fix: /back Command Auto-Completion Issue

## Issue Description

When using the `/back` command iteratively (multiple times), the system would incorrectly behave as if the refinement process was complete and move to synthesis mode, even though the user had navigated back to earlier steps.

## Root Cause

The bug occurred due to the following sequence:

1. User executes `/back` command to return to a previous aspect
2. The `go_back()` function would:
   - Mark the previous step as `is_complete = False`
   - Truncate subsequent steps from the session
   - **BUT** leave the `conversation_history` and `normalized_value` intact
3. When `_build_next_prompt()` is called after the command:
   - It analyzes the reopened step with the LLM
   - The LLM sees the existing `conversation_history` from before
   - The LLM **incorrectly auto-completes** the step, thinking it's already clear
4. After multiple `/back` commands, all reopened steps get auto-completed
5. Eventually `get_next_unrefined_aspect()` returns `None`
6. The system sets `ready_for_synthesis = True`
7. The frontend moves to synthesis mode

## Solution

The fix ensures that when going back to a previous step, all data from that step is cleared, preventing the LLM from auto-completing based on stale data.

### Changes Made

#### 1. Session Commands (`session_commands.py`)

Modified the `go_back()` method to clear all step data:

```python
# Reopen the previous step and clear its data to force fresh refinement
prev_step.is_complete = False
prev_step.needs_review = False
prev_step.follow_up_question = None  # Force question regeneration
prev_step.conversation_history = []  # Clear previous answers
prev_step.normalized_value = None    # Clear assembled value
```

This prevents the LLM from seeing old conversation history and auto-completing the step.

#### 2. API Routes (`api/routes/refinement.py`)

Added database record reset logic after `/back` commands:

```python
# For /back command, also reset the DB record for the reopened aspect
if command_type in ["back", "prev", "previous"]:
    reopened_step = session.get_active_step()
    if reopened_step:
        db_steps = get_query_refinement_steps(db, query_id)
        db_step = next(
            (s for s in db_steps if s.aspect_name == reopened_step.refinement_aspect.aspect_name),
            None
        )
        if db_step:
            reset_refinement_step(db, step_id=db_step.id, clear_followup_history=True)
```

This keeps the database in sync with the in-memory session state.

## Behavior After Fix

After the fix:

1. `/back` clears all data from the reopened step (conversation history, normalized value, question)
2. The step is marked as incomplete
3. When `_build_next_prompt()` analyzes the step, it sees a clean slate
4. The LLM generates a fresh question instead of auto-completing
5. The user can provide new answers without the system prematurely completing the refinement
6. The database record is reset to match the session state

## Testing

A test script has been created at `test_back_issue.py` to verify the fix. The test:

1. Creates a session with 4 complete aspects
2. Executes `/back` multiple times
3. Verifies that reopened steps have cleared data
4. Confirms the session is not marked as complete

## Related Commands

The `/clear` command already had the correct clearing behavior, which this fix aligns with.

## Date

Fixed: February 10, 2026
