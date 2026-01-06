# API Command Integration

## Overview

The Query Refinement API now supports user commands (e.g., `/status`, `/back`, `/goto`, `/skip`) in the answer submission endpoint, providing the same workflow control capabilities available in the CLI.

## Implementation Summary

### 1. New Response Models

#### `CommandResponse`

Added to `query_refinement_module/api/routes/refinement.py`:

```python
class CommandResponse(BaseModel):
    """Response when user issues a command instead of answering."""
    command_type: str  # e.g., "status", "back", "skip"
    success: bool
    message: str
    next_prompt: Optional[Dict[str, Any]]
    
    # Optional fields for specific commands
    invalidated_aspects: Optional[List[str]]  # /back, /goto
    synthesis_ready: Optional[bool]  # /submit
    step_summary: Optional[Dict[str, Any]]  # /status
    step_list: Optional[List[Dict[str, Any]]]  # /steps
    force_required: Optional[bool]  # Navigation with invalidation
```

#### Updated `SubmitAnswerRequest`

Added `force` flag for navigation confirmation:

```python
class SubmitAnswerRequest(BaseModel):
    answer: str  # User's answer or command
    force: Optional[bool] = False  # Force navigation despite invalidation
```

### 2. Endpoint Changes

#### `POST /api/refinement/queries/{query_id}/answer`

- **Response Type**: `Union[SubmitAnswerResponse, CommandResponse]`
- **New Behavior**: Detects commands (input starting with `/`) and routes appropriately

**Command Processing Flow**:
1. Check if input is command using `is_user_command()`
2. Parse command using `parse_user_command()`
3. Execute via `session.handle_command()`
4. Check if force confirmation needed for navigation commands
5. Save session state for state-mutating commands
6. Return `CommandResponse` with appropriate fields

**Regular Answer Processing**:
- Unchanged from original implementation
- Returns `SubmitAnswerResponse`

### 3. Command Types and Behaviors

#### Information Commands (Read-Only)
- `/status` - Returns session progress summary
- `/steps` - Returns list of all refinement steps
- `/help` - Returns command help text

**Behavior**: No session state modification, current prompt preserved

#### Navigation Commands (State-Mutating)
- `/back` or `/prev` - Return to previous step
- `/goto <n>` - Jump to specific step number
- `/restart` - Reset session to initial state

**Behavior**: 
- Modifies session state (completion flags, active step)
- Invalidates dependent aspects
- Requires `force=true` if invalidation occurs (optional confirmation)
- Saves session to Redis
- Returns new active step

#### Control Commands (Workflow Advancing)
- `/skip` - Mark current aspect complete without additional questions
- `/done` - Complete current aspect with collected information

**Behavior**:
- Marks current step complete
- Advances to next aspect
- Saves session to Redis

#### Synthesis Command
- `/submit` or `/end` - Request early synthesis

**Behavior**:
- Sets `synthesis_requested=True` on session
- Returns `synthesis_ready=True`
- Returns `next_prompt=None`
- Client should call `/synthesize` endpoint

### 4. Force Confirmation Feature

Navigation commands that invalidate dependent aspects can require explicit confirmation:

**Without force flag**:
```json
{
  "command_type": "back",
  "success": false,
  "message": "Returned to step 2: Population. This will invalidate 2 dependent aspect(s). Resend with force=true to proceed.",
  "force_required": true,
  "invalidated_aspects": ["Intervention", "Outcome"]
}
```

**With force=true**:
```json
{
  "command_type": "back",
  "success": true,
  "message": "Returned to step 2: Population. Marked for review: Intervention, Outcome",
  "next_prompt": { ... },
  "invalidated_aspects": ["Intervention", "Outcome"]
}
```

## API Examples

### Status Command

**Request**:
```bash
POST /api/refinement/queries/123/answer
{
  "answer": "/status"
}
```

**Response**:
```json
{
  "command_type": "status",
  "success": true,
  "message": "Session Status:\n  Steps: 2/5 complete\n  ...",
  "next_prompt": { ... },
  "step_summary": {
    "total_steps": 5,
    "completed": 2,
    "needs_review": 1,
    "in_progress": 1,
    "total_follow_ups": 3
  }
}
```

### Back Command

**Request**:
```bash
POST /api/refinement/queries/123/answer
{
  "answer": "/back",
  "force": true
}
```

**Response**:
```json
{
  "command_type": "back",
  "success": true,
  "message": "Returned to step 2: Population. Marked for review: Intervention, Outcome",
  "next_prompt": {
    "aspect_id": "population",
    "aspect_name": "Population",
    "question": "What patient population are you studying?",
    "description": "Target demographic or patient group"
  },
  "invalidated_aspects": ["Intervention", "Outcome"]
}
```

### Skip Command

**Request**:
```bash
POST /api/refinement/queries/123/answer
{
  "answer": "/skip"
}
```

**Response**:
```json
{
  "command_type": "skip",
  "success": true,
  "message": "Skipped refinement aspect: Comparison",
  "next_prompt": {
    "aspect_id": "outcome",
    "aspect_name": "Outcome",
    "question": "What outcomes or endpoints are you measuring?",
    "description": "Primary and secondary outcome measures"
  }
}
```

### Submit Command

**Request**:
```bash
POST /api/refinement/queries/123/answer
{
  "answer": "/submit"
}
```

**Response**:
```json
{
  "command_type": "submit",
  "success": true,
  "message": "Ready for synthesis. Call /synthesize endpoint.",
  "next_prompt": null,
  "synthesis_ready": true
}
```

## Testing

Comprehensive integration tests added to `tests/api/test_refinement_endpoints.py`:

- ✅ `test_command_status()` - Status command returns summary
- ✅ `test_command_steps()` - Steps command returns list
- ✅ `test_command_help()` - Help command returns help text
- ✅ `test_command_skip()` - Skip advances workflow
- ✅ `test_command_submit()` - Submit enables synthesis
- ✅ `test_command_back_after_answer()` - Back returns to previous step
- ✅ `test_command_goto_validation()` - Goto validates step number
- ✅ `test_command_invalid()` - Invalid commands properly rejected
- ✅ `test_command_force_confirmation()` - Force confirmation for navigation

**Run tests**:
```bash
# Start API server first
poetry run uvicorn query_refinement_module.api.main:app --reload

# In another terminal
poetry run python tests/api/test_refinement_endpoints.py
```

## Rate Limiting

Commands inherit HTTP rate limiting from middleware (default: 60 req/min):

- **Information commands** (`/status`, `/help`, `/steps`): No LLM calls, only HTTP rate limit
- **Navigation commands** (`/back`, `/goto`, `/restart`): No immediate LLM calls, only HTTP rate limit
- **Control commands** (`/skip`, `/done`): May trigger LLM for next aspect analysis (LLM rate limit applies)
- **Synthesis command** (`/submit`): No LLM call (synthesis happens separately)

## Session State Management

### Redis Persistence

Commands that modify session state trigger immediate Redis save:
- `/back`, `/prev`, `/goto`, `/restart` - Navigation state changes
- `/skip`, `/done` - Completion state changes
- `/submit`, `/end` - Synthesis request flag

### Database Persistence

- **No immediate DB changes**: Commands modify transient session state in Redis
- **DB writes on next answer**: When user provides an answer after navigation, new `FollowUp` entries created
- **Audit trail preserved**: Previous follow-ups remain in DB, session tracks "active" state

### Session Reconstruction

If session expires from Redis (TTL):
- Reconstructed from database `RefinementStep` and `FollowUp` records
- Shows "last answered state" not "last navigated state"
- Navigation history not persisted (by design - transient workflow control)

## Frontend Integration Guide

### Detecting Response Type

```typescript
interface BaseResponse {
  // Common fields for discrimination
}

interface CommandResponse extends BaseResponse {
  command_type: string;
  success: boolean;
  message: string;
  next_prompt?: object;
  invalidated_aspects?: string[];
  synthesis_ready?: boolean;
  step_summary?: object;
  step_list?: object[];
  force_required?: boolean;
}

interface AnswerResponse extends BaseResponse {
  refinement_step_id: number;
  followup_id: number;
  is_complete: boolean;
  next_prompt?: object;
}

function isCommandResponse(response: any): response is CommandResponse {
  return 'command_type' in response;
}
```

### Handling Commands

```typescript
const response = await submitAnswer(queryId, userInput);

if (isCommandResponse(response)) {
  // Handle command
  if (response.force_required) {
    // Show confirmation dialog
    const confirmed = await showInvalidationWarning(
      response.invalidated_aspects
    );
    
    if (confirmed) {
      // Resubmit with force=true
      await submitAnswer(queryId, userInput, { force: true });
    }
  } else if (response.synthesis_ready) {
    // Navigate to synthesis
    await synthesizeQuery(queryId);
  } else {
    // Show command result
    showMessage(response.message);
    
    // Update UI with command-specific data
    if (response.step_summary) {
      updateProgressDisplay(response.step_summary);
    }
  }
} else {
  // Handle regular answer
  if (response.next_prompt) {
    displayNextQuestion(response.next_prompt);
  }
}
```

## Migration Notes

### Backward Compatibility

- ✅ Existing answer submission flow unchanged
- ✅ Non-command answers processed identically
- ✅ Response structure extended (Union type), not replaced
- ✅ No database schema changes required

### Breaking Changes

None. The API is backward compatible with existing clients. Clients that don't send commands will receive `SubmitAnswerResponse` as before.

## Future Enhancements

1. **Session state persistence**: Add `session_state` JSONB column to `Query` table for full navigation history
2. **Real-time command suggestions**: Return available commands in `next_prompt` based on session state
3. **Command aliases in response**: Show both command and aliases in help text
4. **Undo stack**: Implement multi-level undo beyond single `/back`
5. **Command permissions**: Role-based command access (e.g., admin-only `/restart`)

## See Also

- [User Commands Documentation](user_commands.md) - Complete command reference
- [API Service Overview](api_service.md) - General API architecture
- [API Integration Guide](api_integration_guide.md) - Client integration patterns
