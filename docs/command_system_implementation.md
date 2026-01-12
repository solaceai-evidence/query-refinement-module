# Command System Implementation

## Overview
This document describes the comprehensive command system implementation with all 10 user commands, enhanced UI components, and full traceability logging.

## Commands Implemented

### Information Commands
- **`/status`** - View progress summary with completed/pending aspects
- **`/steps`** - List all refinement steps with detailed status
- **`/help`** - Show available commands with descriptions

### Control Commands
- **`/skip`** - Skip current question and move to next
- **`/done`** - Mark current step complete and stop follow-ups
- **`/submit`** or **`/end`** - Finish refinement session now

### Navigation Commands
- **`/back`** - Go to previous question
- **`/goto <number>`** - Jump to specific step by number
- **`/restart`** - Start refinement from beginning

## Frontend Components

### 1. CommandButtons.jsx
**Location**: `frontend/src/components/CommandButtons.jsx`

**Features**:
- Organized into 3 sections: Info, Control, Navigation
- 9 quick-action buttons + interactive Go To prompt
- Icons and tooltips for each command
- Category-based layout for better UX
- Disabled state during processing

**Usage**:
```jsx
<CommandButtons
    onCommand={handleCommand}
    disabled={loading}
/>
```

### 2. CommandHistoryItem.jsx (NEW)
**Location**: `frontend/src/components/CommandHistoryItem.jsx`

**Purpose**: Dedicated component for displaying executed commands in conversation history

**Features**:
- Visual distinction with gradient background
- Command type badge and icon
- Success/error state indication
- Expandable result details including:
  - Command message
  - Progress summary (completed/total/pending)
  - Step list with status badges
  - Warning for invalidated aspects
- Animated entry with slideIn effect

**Props**:
```typescript
interface CommandHistoryItemProps {
    command: string;           // e.g., "/skip"
    result?: {
        type: string;          // Command type
        message: string;       // Result message
        success: boolean;      // Success indicator
        step_summary?: {       // Progress info
            completed_steps: number;
            total_steps: number;
            pending_steps: number;
        };
        step_list?: Array<{    // Detailed steps
            aspect_name: string;
            status: string;
            is_active: boolean;
        }>;
        invalidated_aspects?: string[];  // Affected aspects
    };
}
```

**Visual States**:
- **Pending**: Gray gradient (command sent, awaiting result)
- **Success**: Purple gradient with white text
- **Error**: Red gradient with error styling

## Frontend Logging

### Trace Points
All logging prefixed with `[TRACE]`, `[COMMAND TRACE]`, `[COMMAND RESPONSE]`, or `[ERROR]`

#### 1. handleAnswer Function
```javascript
console.log('[TRACE] handleAnswer called with:', answer);
console.log('[TRACE] Is command:', answer.startsWith('/'));
```

#### 2. Command Detection
```javascript
console.log('[COMMAND TRACE] Adding command to history:', answer);
```

#### 3. API Response
```javascript
console.log('[TRACE] Response received:', {
    hasCommandType: !!response.command_type,
    commandType: response.command_type,
    hasNextPrompt: !!response.next_prompt,
    nextPromptAspectName: response.next_prompt?.aspect_name,
    hasQuestion: !!response.next_prompt?.question
});
```

#### 4. Command Result Processing
```javascript
console.log('[COMMAND RESPONSE] Type: ${response.command_type}, Success: ${response.success}');
console.log('[COMMAND RESPONSE] Message:', response.message);
console.log('[COMMAND RESPONSE] Setting command result:', commandResultData);
```

#### 5. Next Question Handling
```javascript
console.log('[COMMAND RESPONSE] Adding new question to history');
console.log('[COMMAND RESPONSE] Question preview:', response.next_prompt.question.substring(0, 100));
```

#### 6. Error Handling
```javascript
console.error('[ERROR] Error in handleAnswer:', err);
console.error('[ERROR] Error response:', err.response?.data);
```

### handleCommand Function
```javascript
console.log('[COMMAND HANDLER] User clicked command:', command);
console.log('[COMMAND HANDLER] Current sessionId:', sessionId);
console.log('[COMMAND HANDLER] Current queryId:', queryId);
console.log('[COMMAND HANDLER] Current aspectId:', currentAspectId);
```

## Backend Logging

### Trace Points in refinement.py

#### 1. Input Processing
```python
logger.info(f"[Query {query_id}] Processing answer/command: {user_input[:100]}...")
logger.info(f"[Query {query_id}] Is command: {is_user_command(user_input)}")
```

#### 2. Command Detection
```python
logger.info(f"[Query {query_id}] COMMAND DETECTED: {user_input}")
```

#### 3. Command Parsing
```python
logger.info(f"[Query {query_id}] Command parsed - valid: {cmd_result.is_valid}, command: {cmd_result.command}, arg: {cmd_result.arg}")
```

#### 4. Invalid Command
```python
logger.warning(f"[Query {query_id}] Invalid command: {cmd_result.error_message}")
```

#### 5. Command Execution
```python
logger.info(f"[Query {query_id}] Executing command: {cmd_result.command.value}")
logger.info(f"[Query {query_id}] Command result - success: {command_payload.get('success')}, message: {command_payload.get('message', '')[:100]}")
```

#### 6. Force Confirmation
```python
logger.info(f"[Query {query_id}] Force confirmation needed - would invalidate: {invalidated}")
```

#### 7. Session Persistence
```python
logger.info(f"[Query {query_id}] Saving session state after command: {command_type}")
```

### _build_command_response Logging

#### Entry Point
```python
logger.info(f"[_build_command_response] Building response for command: {command_type}")
logger.info(f"[_build_command_response] Command success: {success}, message: {message[:100]}")
```

#### Command-Specific Handling
```python
# STATUS
logger.info(f"[_build_command_response] STATUS command - adding step summary")

# STEPS
logger.info(f"[_build_command_response] STEPS command - building step list")
logger.info(f"[_build_command_response] Built step list with {len(response.step_list)} steps")

# NAVIGATION
logger.info(f"[_build_command_response] NAVIGATION command ({command_type}) - building next prompt")
logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")

# CONTROL (skip/done)
logger.info(f"[_build_command_response] CONTROL command ({command_type}) - advancing to next step")
logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('aspect_name')}, has question: {has_question}")
logger.info(f"[_build_command_response]   -> Question preview: {response.next_prompt.get('question')[:100]}")
```

## Conversation History Structure

### History Item Types

#### 1. Query
```javascript
{
    type: 'query',
    content: string,
    timestamp: ISO8601
}
```

#### 2. Question
```javascript
{
    type: 'question',
    content: string,
    aspectId: string,
    aspectName: string,
    timestamp: ISO8601
}
```

#### 3. Answer
```javascript
{
    type: 'answer',
    content: string,
    aspectId: string,
    timestamp: ISO8601
}
```

#### 4. Command (NEW)
```javascript
{
    type: 'command',
    content: string,        // e.g., "/skip"
    aspectId: string,
    timestamp: ISO8601,
    result?: {              // Added after API response
        type: string,
        message: string,
        success: boolean,
        step_summary?: {...},
        step_list?: [...],
        invalidated_aspects?: [...]
    }
}
```

## CSS Styling

### CommandHistoryItem.css
- Gradient backgrounds (purple for success, red for error, gray for pending)
- Animated entry with `slideInCommand` keyframe
- Responsive step badges with color coding
- Hover effects with transforms
- Status indicators (active, complete, pending)

### CommandButtons.css
- Sectioned layout with category labels
- Consistent button styling across all commands
- Hover states with color transitions
- Disabled state styling
- Responsive flex layout

### Refinement.css Updates
- Enhanced history items with gradients
- Emoji icons in labels
- Improved animation (`fadeInUp`)
- Hover effects on history items
- Better spacing and typography

## Debugging Guide

### Frontend Debugging
1. Open browser DevTools (F12)
2. Go to Console tab
3. Filter by `[TRACE]`, `[COMMAND]`, or `[ERROR]`
4. Execute a command
5. Observe:
   - Command detection
   - API call
   - Response structure
   - History updates
   - UI state changes

### Backend Debugging
1. Monitor backend.log:
   ```bash
   tail -f backend.log | grep "COMMAND\|_build_command_response"
   ```
2. Execute a command from frontend
3. Observe:
   - Input detection
   - Command parsing
   - Execution result
   - Response building
   - Session persistence

### Common Issues & Solutions

#### Issue: Command doesn't show result
**Check**: Browser console for `[COMMAND RESPONSE]` logs
**Solution**: Verify API returns `command_type` field

#### Issue: Next question not appearing
**Check**: Backend log for `next_prompt` existence
**Solution**: Verify `_build_next_prompt()` returns valid question

#### Issue: History not updating
**Check**: Frontend console for history array updates
**Solution**: Verify `setConversationHistory` is called with correct structure

## Testing Checklist

### Information Commands
- [ ] `/status` shows current progress
- [ ] `/steps` displays all steps with correct status
- [ ] `/help` lists all commands

### Control Commands
- [ ] `/skip` moves to next question
- [ ] `/done` marks step complete
- [ ] `/submit` triggers synthesis

### Navigation Commands
- [ ] `/back` goes to previous question
- [ ] `/restart` goes to first question
- [ ] `/goto 2` jumps to step 2

### UI/UX
- [ ] Command appears in history with gradient background
- [ ] Result shows with correct icon and message
- [ ] Step list displays with color coding
- [ ] Progress summary shows accurate counts
- [ ] Animations play smoothly
- [ ] Scrolling works correctly

### Logging
- [ ] Frontend console shows all trace points
- [ ] Backend log shows command lifecycle
- [ ] Timestamps are accurate
- [ ] Error cases logged properly

## Performance Considerations

- **History Size**: Consider limiting conversation history to last N items for long sessions
- **Rendering**: CommandHistoryItem uses React keys with timestamps for efficient updates
- **Logging**: Production builds should reduce console.log verbosity
- **Animations**: CSS animations are hardware-accelerated (transform, opacity)

## Future Enhancements

1. **Command Autocomplete**: Type `/` to show command suggestions
2. **Keyboard Shortcuts**: Map keys to common commands
3. **Command History**: Arrow up/down to recall previous commands
4. **Undo/Redo**: Allow reverting commands with `/undo`
5. **Export History**: Download conversation as JSON/PDF
6. **Search History**: Filter/search through conversation
7. **Batch Commands**: Execute multiple commands at once
8. **Custom Commands**: Allow users to define shortcuts

## Architecture Diagram

```
┌─────────────────┐
│  User Input     │
│  "/skip"        │
└────────┬────────┘
         │
         v
┌─────────────────────────┐
│  CommandButtons.jsx     │
│  - Detects command      │
│  - Calls onCommand()    │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Refinement.jsx         │
│  handleCommand()        │
│  - Logs command         │
│  - Adds to history      │
│  - Calls handleAnswer() │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  API Call               │
│  continueRefinement()   │
│  - Sends to backend     │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Backend                │
│  refinement.py          │
│  - Detects command      │
│  - Parses command       │
│  - Executes via session │
│  - Builds response      │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Response               │
│  CommandResponse        │
│  - command_type         │
│  - success              │
│  - message              │
│  - next_prompt          │
│  - step_summary/list    │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Frontend Updates       │
│  - Updates history      │
│  - Attaches result      │
│  - Renders Component    │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  CommandHistoryItem     │
│  - Displays command     │
│  - Shows result         │
│  - Renders details      │
└─────────────────────────┘
```

## File Manifest

### New Files
- `frontend/src/components/CommandHistoryItem.jsx`
- `frontend/src/components/CommandHistoryItem.css`
- `docs/command_system_implementation.md` (this file)

### Modified Files
- `frontend/src/components/CommandButtons.jsx` - Added 6 commands, categorized layout
- `frontend/src/components/CommandButtons.css` - Updated styling for sections
- `frontend/src/pages/Refinement.jsx` - Enhanced logging, command history integration
- `frontend/src/pages/Refinement.css` - Improved history item styling
- `query_refinement_module/api/routes/refinement.py` - Comprehensive logging

## Version History
- **v1.0** (2026-01-12): Initial implementation with all 10 commands, CommandHistoryItem component, comprehensive logging
