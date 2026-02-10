# Session Abandonment (Start Over) - Implementation Summary

## Overview

Implemented comprehensive session abandonment functionality so that when users click "Start Over", their previous incomplete session is completely deleted from the database and doesn't count toward workflow limits.

## Problem

Previously, clicking "Start Over" only cleared the frontend UI state. The backend session and all associated data remained in the database, causing:
- Previous incomplete sessions to count toward workflow limits
- Database accumulation of abandoned incomplete sessions
- Confusion when users wanted to truly start fresh

## Solution

Created a complete cleanup mechanism that:
1. **Deletes all session data from database** when user clicks "Start Over"
2. **Ensures abandoned sessions don't count** toward workflow limits
3. **Clears Redis cache** naturally via TTL expiration
4. **Preserves audit logs** for research purposes

## Changes Made

### 1. Backend - Database CRUD Function

**File:** `query_refinement_module/db/crud.py`

Added `abandon_query_session()` function that:
- Verifies user owns the session (authorization)
- Deletes all related data in correct order (respects foreign keys):
  - FollowUpHistory entries
  - RefinementStepMetadata entries  
  - RefinementSteps
  - Feedback
  - Queries
  - QuerySession itself
- Preserves AuditLog and FrontendLog for research
- Returns deletion counts for verification
- Comprehensive logging of all operations

### 2. Backend - API Endpoint

**File:** `query_refinement_module/api/routes/refinement.py`

Added `POST /api/refinement/sessions/abandon` endpoint that:
- Accepts session_id to abandon
- Validates user authorization
- Calls CRUD function to delete data
- Logs audit event (SESSION_ABANDONED)
- Returns detailed deletion counts
- Handles errors gracefully

**Request:**
```json
{
  "session_id": 123
}
```

**Response:**
```json
{
  "status": "success",
  "session_id": 123,
  "deletion_counts": {
    "followups": 5,
    "step_metadata": 3,
    "refinement_steps": 3,
    "feedback": 0,
    "queries": 1,
    "session": 1
  },
  "message": "Session 123 abandoned successfully. Deleted 1 queries, 3 refinement steps."
}
```

### 3. Backend - Audit Event Type

**File:** `query_refinement_module/db/models/audit_log.py`

Added `SESSION_ABANDONED = "session.abandoned"` event type for tracking when sessions are abandoned.

### 4. Frontend - API Service

**File:** `frontend/src/services/refinement.js`

Added `abandonSession(sessionId)` method that:
- Calls the backend abandon endpoint
- Logs the operation
- Handles errors gracefully
- Returns deletion results

### 5. Frontend - UI Handler

**File:** `frontend/src/pages/Refinement.jsx`

Updated `handleStartOver()` function to:
- Call `refinementService.abandonSession()` if sessionId exists
- Log success/failure
- Continue with UI reset even if API call fails
- Clear localStorage and all UI state
- Return user to framework selection

**Before:**
```javascript
const handleStartOver = () => {
    clearSession();  // Only cleared localStorage
    // ... reset UI state
};
```

**After:**
```javascript
const handleStartOver = async () => {
    if (sessionId) {
        try {
            await refinementService.abandonSession(sessionId);
            console.log('Session abandoned successfully');
        } catch (error) {
            console.error('Failed to abandon session:', error);
            // Continue with UI reset anyway
        }
    }
    clearSession();
    // ... reset UI state
};
```

### 6. Testing

**File:** `tests/api/test_abandon_session.py`

Comprehensive test that verifies:
- Session can be abandoned via API
- All related data is deleted from database
- Deletion counts are accurate
- Query status returns 404 after abandonment
- User can start new session after abandoning (doesn't count toward limit)

**File:** `test_abandon.sh`

Quick test script for easy manual testing.

## Data Deletion Flow

When a session is abandoned:

```
1. User clicks "Start Over" in UI
   ↓
2. Frontend calls abandonSession(sessionId)
   ↓
3. Backend receives POST /api/refinement/sessions/abandon
   ↓
4. Validates user owns the session
   ↓
5. Deletes data in order (respecting foreign keys):
   a. FollowUpHistory (linked to RefinementSteps)
   b. RefinementStepMetadata (linked to RefinementSteps)
   c. RefinementSteps (linked to Queries)
   d. Feedback (linked to Queries)
   e. Queries (linked to QuerySession)
   f. QuerySession itself
   ↓
6. Logs SESSION_ABANDONED audit event
   ↓
7. Returns deletion counts to frontend
   ↓
8. Frontend clears localStorage and UI state
   ↓
9. User sees framework selection screen (fresh start)
```

## What's Preserved

For research purposes, these are **NOT deleted**:
- **AuditLog entries** - Tracks all user actions including abandonment
- **FrontendLog entries** - UI interaction logs
- **User account** - User can continue with new sessions

## Testing Instructions

### Manual Testing (UI)

1. Start the backend:
   ```bash
   poetry run uvicorn query_refinement_module.api.main:app --reload
   ```

2. Start the frontend:
   ```bash
   cd frontend && npm run dev
   ```

3. In browser (http://localhost:5173):
   - Login/register
   - Start a refinement session
   - Answer 1-2 questions
   - Click "Start Over" button
   - Verify you're back at framework selection
   - Start a new session (should work, not blocked by limit)

4. Check browser console for:
   ```
   [Refinement] Attempting to abandon session 123
   [Refinement] Session abandoned successfully
   [Refinement] State cleared, returning to framework selection
   ```

### Automated Testing

Run the comprehensive test:
```bash
./test_abandon.sh
```

Or directly:
```bash
poetry run python tests/api/test_abandon_session.py
```

Expected output:
```
✅ ALL TESTS PASSED
Session abandonment is working correctly:
  ✓ Session data is deleted from database
  ✓ Abandoned sessions don't count toward limits
  ✓ User can start new session after abandoning
```

## Workflow Limits

With this implementation, abandoned sessions **do not count** toward workflow limits because:
- The QuerySession record is deleted
- When checking limits, only existing QuerySessions are counted
- User can abandon and restart without penalty

Example limit check logic:
```python
# Count only existing sessions (abandoned ones are deleted)
session_count = db.query(QuerySession).filter(
    QuerySession.user_id == user_id,
    QuerySession.status != "abandoned"  # Not needed anymore since deleted
).count()

can_start_new = session_count < limit
```

## Benefits

1. **Clean Database** - No accumulation of incomplete abandoned sessions
2. **Accurate Limits** - Only active/completed sessions count
3. **User Clarity** - "Start Over" truly starts fresh
4. **Research Data** - Audit logs preserve abandonment events
5. **Performance** - Reduced database size from cleanup

## Error Handling

All operations include comprehensive error handling:

- **Session not found:** Returns 404
- **Unauthorized:** Returns 404 (session doesn't belong to user)
- **Database errors:** Returns 500 with error message
- **Frontend errors:** Logs but continues with UI reset

## Backwards Compatibility

- Old sessions without abandonment still work
- Existing sessions can be abandoned
- No migration needed
- API is additive (new endpoint only)

## Future Enhancements

Possible improvements:
1. Add a "Resume Session" option before abandoning
2. Add confirmation dialog: "Are you sure you want to abandon?"
3. Show deletion counts in UI feedback
4. Add bulk abandonment for admins
5. Add soft-delete option (mark as abandoned but keep data)

## Files Modified

### Backend
- `query_refinement_module/db/crud.py` - Added `abandon_query_session()`
- `query_refinement_module/api/routes/refinement.py` - Added abandon endpoint
- `query_refinement_module/db/models/audit_log.py` - Added SESSION_ABANDONED event

### Frontend
- `frontend/src/services/refinement.js` - Added `abandonSession()` method
- `frontend/src/pages/Refinement.jsx` - Updated `handleStartOver()` to call API

### Tests
- `tests/api/test_abandon_session.py` - Comprehensive test (NEW)
- `test_abandon.sh` - Quick test script (NEW)

## Summary

This implementation ensures that "Start Over" properly cleans up abandoned sessions from the database, preventing them from counting toward workflow limits while preserving audit trails for research purposes. The solution is robust, well-tested, and user-friendly.
