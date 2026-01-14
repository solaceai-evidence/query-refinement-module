# Debugging Guide for Query Refinement Web App

## Quick Reference

### 1. **Check Backend Logs**
```bash
tail -f backend.log | grep -E "(ERROR|Exception|Traceback|POST|GET)"
```

### 2. **Check Frontend Console**
Open browser DevTools → Console tab to see React errors and our debug logs

### 3. **Test API Without Frontend**
```bash
poetry run python test_frontend_workflow.py
```

## Common Issues & Solutions

### Issue: Blank Page After Login

**Symptoms:**
- Page loads but shows nothing
- No errors in console
- Backend shows successful responses

**Causes:**
1. Component rendering conditional failed (e.g., `currentQuestion && currentQuestion.question` when question is null/empty)
2. Missing required data in state
3. CSS hiding content

**Solution:**
- Check browser console for errors
- Verify all conditionals have proper null checks
- Use test script to see actual API response structure

---

### Issue: App Gets Stuck "Thinking"

**Symptoms:**
- Loading spinner stays active
- No new question appears
- No error message

**Causes:**
1. Backend returns empty `question` field in `next_prompt`
2. Frontend error in async handler not properly caught
3. LLM service timeout or failure

**Debugging Steps:**
1. Check browser Network tab → find the `/answer` request → see response
2. Run test script to see what backend actually returns
3. Check backend logs for LLM errors
4. Verify `refinement_question` is not null in response

**Fix Applied:**
- Backend: Don't overwrite `refinement_question` with empty/null `followup_question`
- Frontend: Added null checks and console logging

---

### Issue: Command Results Not Showing

**Symptoms:**
- Click status/help button but nothing appears
- Or command result pushes content around

**Solution:**
- Verify `commandResult` state is being set
- Check `response.command_type` exists
- Ensure CommandButtons is positioned correctly (below QuestionRenderer)

---

## Testing Strategy

### 1. Backend API Testing (Existing)
```bash
# Run existing endpoint tests
poetry run pytest tests/api/test_refinement_endpoints.py -v
```

### 2. Integration Testing (New)
```bash
# Test complete workflow without frontend
poetry run python test_frontend_workflow.py
```

**What it tests:**
- Auth flow
- Framework selection  
- Start refinement
- Submit answer
- Check status
- Execute commands

**Output shows:**
- HTTP status codes
- Full response bodies
- ⚠️ warnings for empty/null fields that would break frontend

### 3. Frontend Testing (Manual)
1. Open browser DevTools → Console
2. Watch for console.log messages we added:
   - `'Response received:'` - shows full API response
   - `'next_prompt.question:'` - shows question value
   - `'next_prompt.question is null/undefined:'` - flags the problem

### 4. End-to-End Testing (Manual)
1. Register/Login
2. Select framework
3. Enter initial query
4. Answer first question
5. Try each command button
6. Complete refinement
7. Submit feedback

---

## Logging Strategy

### Backend Logging
Currently using Python `logging` module:
- INFO: Request start/end
- WARNING: Recoverable issues
- ERROR: Failures, exceptions

**Improvement Needed:**
Add structured logging for key decision points:
```python
logger.debug(f"refinement_question before: {step.refinement_question}")
logger.debug(f"followup_question from LLM: {followup_question}")
logger.debug(f"refinement_question after: {step.refinement_question}")
```

### Frontend Logging  
Added console.log statements in critical paths:
- Response structure
- Null/undefined checks
- Error details

**For Production:**
Replace console.log with proper logging service (e.g., Sentry, LogRocket)

---

## Code Quality Checks

### Before Each Feature
1. Run test script: `poetry run python test_frontend_workflow.py`
2. Check no TypeScript/ESLint errors
3. Test manually in browser

### After Each Fix
1. Verify fix with test script first
2. Then test in browser
3. Check no regression in other features

---

## Architecture Notes

### Backend Flow
```
POST /api/refinement/start
  → manager.initialize() - analyzes all aspects, generates questions
  → saves session to Redis
  → returns first question

POST /api/refinement/queries/{id}/answer
  → loads session from Redis
  → run_followup_until_clear() - LLM asks follow-ups
  → updates refinement_question
  → saves to Redis
  → returns next question or marks complete
```

### Frontend Flow
```
Login → Refinement Page
  → Select Framework → Submit Initial Query
    → handleInitialQuerySubmit()
      → startRefinement API
      → sets currentQuestion, aspects, stage='refinement'
  
  → Answer Question → handleAnswer()
    → continueRefinement API
    → if command_type: show command result
    → else: update conversation, show next question
    → updateAspectStatus() to refresh sidebar
```

### Key State Variables
- `currentQuestion`: Object with {aspect_id, aspect_name, question, description}
- `currentQuestion.question`: **CRITICAL** - must not be null/empty or nothing renders
- `commandResult`: Holds command output for display
- `aspects`: Array for sidebar progress panel
- `conversationHistory`: Array of Q&A for display

---

## Future Improvements

### 1. Automated Frontend Testing
```bash
npm install --save-dev @testing-library/react @testing-library/jest-dom vitest
```

Create `frontend/src/pages/Refinement.test.jsx`:
```javascript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Refinement from './Refinement';

test('shows question after submitting initial query', async () => {
  // Mock API calls
  // Render component
  // Simulate user actions
  // Assert question appears
});
```

### 2. Better Error Boundaries
Add React Error Boundary to catch and display component errors gracefully

### 3. API Response Validation
Use Zod or similar to validate API responses match expected schema before using

### 4. Monitoring & Alerting
- Add Sentry for frontend error tracking
- Add backend performance monitoring
- Alert on high error rates

---

## Quick Fixes Applied

### 1. Backend: Empty Question Prevention
**File:** `query_refinement_module/core.py`
**Line:** ~979
**Fix:** Only update `refinement_question` if `followup_question` is not empty

### 2. Frontend: Null Checks
**File:** `frontend/src/pages/Refinement.jsx`
**Fix:** 
- Check `currentQuestion && currentQuestion.question` before rendering
- Don't add to history if question is null/empty
- Added console logging for debugging

### 3. Frontend: Command Button Positioning
**File:** `frontend/src/pages/Refinement.jsx`
**Fix:** Moved CommandButtons below QuestionRenderer to prevent layout shift

### 4. Frontend: Better Error Handling
**File:** `frontend/src/pages/Refinement.jsx`
**Fix:** Log full error object, not just message

---

## When Things Go Wrong

### Step 1: Isolate the Layer
- Backend issue? Test with `test_frontend_workflow.py`
- Frontend issue? Check browser console
- API contract issue? Compare request/response structures

### Step 2: Add Targeted Logging
- Backend: Add logger.debug() statements
- Frontend: Add console.log() statements
- Focus on state transitions and data flow

### Step 3: Test in Isolation
- Backend: Write focused unit test
- Frontend: Mock API, test component alone
- Integration: Use test script

### Step 4: Fix Root Cause
- Don't patch symptoms
- Understand why it broke
- Add test to prevent regression

---

## Contact Points for Debugging

1. **Backend logs:** `./backend.log`
2. **Frontend console:** Browser DevTools → Console
3. **Network traffic:** Browser DevTools → Network
4. **Database:** `query_refinement.db` (use SQLite browser)
5. **Redis:** Check if using Redis, session data stored there

---

## Success Metrics

### All Systems Working When:
✅ Test script runs without warnings  
✅ Browser console shows no errors  
✅ Each question displays text (not empty)  
✅ Command buttons show results  
✅ Progress panel updates after answers  
✅ Synthesis generates refined query  
✅ Feedback submits successfully  

---

*Last Updated: January 7, 2026*
*Version: 1.0*
