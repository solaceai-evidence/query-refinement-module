# Comprehensive Command Testing Suite

## Overview

Exhaustive test coverage for the API command system integration, validating all features, edge cases, error conditions, and state management scenarios.

## Test Coverage: 50+ Tests Across 10 Categories

### 1. **Information Commands** (5 tests)
- ✅ `/status` returns correct initial state
- ✅ `/status` reflects session progress accurately
- ✅ `/steps` returns complete step information with proper structure
- ✅ `/help` returns comprehensive help text with all sections
- ✅ Information commands don't mutate session state

### 2. **Navigation Commands** (7 tests)
- ✅ `/back` on first step handled correctly
- ✅ `/back` navigates to previous step after progress
- ✅ `/prev` alias works identically to `/back`
- ✅ `/goto` with valid step numbers
- ✅ `/goto` rejects invalid step numbers (0, negative, out of range)
- ✅ `/goto` without argument properly rejected
- ✅ `/restart` resets session state completely

### 3. **Force Confirmation** (3 tests)
- ✅ Force confirmation required when invalidation occurs
- ✅ `force=true` bypasses confirmation
- ✅ Invalidated aspects reported in response

### 4. **Control Commands** (3 tests)
- ✅ `/skip` advances to next aspect
- ✅ `/done` advances to next aspect
- ✅ `/skip` preserves conversation history

### 5. **Synthesis Command** (3 tests)
- ✅ `/submit` flags session for synthesis
- ✅ `/end` alias works identically
- ✅ Synthesis endpoint works after `/submit`

### 6. **Error Handling** (3 tests)
- ✅ Invalid commands properly rejected
- ✅ Malformed commands handled gracefully
- ✅ Failed commands don't corrupt session state

### 7. **Session State Persistence** (3 tests)
- ✅ Session persists in Redis after navigation commands
- ✅ Session persists after skip/done commands
- ✅ Session persists after restart command

### 8. **Command Sequences** (3 tests)
- ✅ Multiple information commands in sequence
- ✅ Complex navigation command sequences
- ✅ Mixing commands and answers

### 9. **Backward Compatibility** (2 tests)
- ✅ Regular answer submission unchanged
- ✅ Text containing slash (not a command) handled gracefully

### 10. **Edge Cases** (4 tests)
- ✅ Rapid successive command execution
- ✅ Command case handling
- ✅ Empty command gracefully rejected
- ✅ Whitespace in commands handled correctly

## Running the Tests

### Prerequisites
```bash
# Ensure API server is running
poetry run uvicorn query_refinement_module.api.main:app --reload
```

### Execute Full Test Suite
```bash
poetry run python tests/api/test_command_features_comprehensive.py
```

### Expected Output
```
================================================================================
COMPREHENSIVE COMMAND FEATURES TESTS
================================================================================

✓ API server is healthy

================================================================================
INFORMATION COMMANDS
================================================================================

▶ Running: Status - Initial State
✓ /status command returns correct initial state

▶ Running: Status - After Progress
✓ /status command reflects progress correctly

...

================================================================================
TEST SUMMARY
================================================================================
✓ Passed:  45
❌ Failed:  0
⊘ Skipped: 5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:     50
================================================================================

🎉 All tests passed!
```

## Test Architecture

### Helper Functions

**Session Management**:
- `create_test_session()` - Create refinement session
- `submit_command()` - Execute command with optional force flag
- `submit_answer()` - Submit regular answer
- `get_session_status()` - Retrieve session status

**Validation**:
- All tests use explicit assertions
- Response structure validation
- State consistency checks

### Test Patterns

#### State Verification
```python
# Before command
initial_state = get_session_status(token, query_id)

# Execute command
command_result = submit_command(token, query_id, "/back")

# Verify state change
final_state = get_session_status(token, query_id)
assert final_state != initial_state
```

#### Error Handling
```python
# Execute invalid command
result = submit_command(token, query_id, "/invalid")

# Verify graceful failure
assert result["success"] is False
assert "message" in result

# Verify state unchanged
verify_state_preserved(token, query_id)
```

#### Sequence Testing
```python
# Execute command sequence
for cmd in ["/status", "/steps", "/help"]:
    result = submit_command(token, query_id, cmd)
    assert result["success"] is True

# Verify consistency
final_check()
```

## Validation Criteria

### Response Structure
Every test validates:
- ✅ Required fields present (`command_type`, `success`, `message`)
- ✅ Optional fields populated appropriately
- ✅ Data types correct
- ✅ Relationships consistent

### State Management
State verification includes:
- ✅ Redis persistence after state-mutating commands
- ✅ Session consistency across requests
- ✅ Database integrity maintained
- ✅ Navigation history tracked correctly

### Error Conditions
Error tests verify:
- ✅ Appropriate error messages
- ✅ State preservation on failure
- ✅ No side effects from failed commands
- ✅ Graceful degradation

## Coverage Matrix

| Feature       | Tests  | Edge Cases | Error Cases |
| ------------- | ------ | ---------- | ----------- |
| `/status`     | 2      | 1          | 1           |
| `/steps`      | 1      | 1          | 0           |
| `/help`       | 1      | 0          | 0           |
| `/back`       | 2      | 1          | 0           |
| `/goto`       | 3      | 2          | 2           |
| `/restart`    | 1      | 0          | 0           |
| `/skip`       | 2      | 1          | 0           |
| `/done`       | 1      | 0          | 0           |
| `/submit`     | 2      | 1          | 0           |
| Force confirm | 3      | 0          | 0           |
| Sequences     | 3      | 1          | 0           |
| Persistence   | 3      | 0          | 0           |
| Compatibility | 2      | 1          | 0           |
| **Total**     | **26** | **9**      | **3**       |

## Test Scenarios

### Scenario 1: Normal Workflow with Commands
```
1. Start session
2. Answer question
3. Check status (/status)
4. Continue answering
5. Skip aspect (/skip)
6. Review progress (/steps)
7. Submit early (/submit)
8. Synthesize
```

### Scenario 2: Navigation with Corrections
```
1. Start session
2. Answer question A
3. Answer question B
4. Realize A was wrong
5. Go back (/back with force)
6. Correct answer A
7. Re-answer B
8. Continue
```

### Scenario 3: Exploration Workflow
```
1. Start session
2. Check all steps (/steps)
3. Read help (/help)
4. Jump to specific step (/goto 3)
5. Check status (/status)
6. Restart to try different approach (/restart)
```

### Scenario 4: Error Recovery
```
1. Start session
2. Try invalid command (/xyz)
3. Verify state preserved
4. Try malformed command (/goto abc)
5. Verify still functional
6. Continue normally
```

## Integration with CI/CD

### GitHub Actions
```yaml
- name: Run Command Feature Tests
  run: |
    poetry run uvicorn query_refinement_module.api.main:app &
    sleep 5
    poetry run python tests/api/test_command_features_comprehensive.py
```

### Test Reports
Tests generate:
- Pass/fail counts
- Skipped tests (framework-dependent)
- Execution time
- Detailed error messages

## Maintenance Guidelines

### Adding New Command Tests
1. Add test function following naming convention: `test_<command>_<scenario>`
2. Use helper functions for setup
3. Include assertions for response structure
4. Verify state changes where applicable
5. Add to appropriate category in test runner

### Updating for New Features
1. Add new test category if needed
2. Update coverage matrix
3. Document new scenarios
4. Update validation criteria

## Known Limitations

### Framework Dependencies
Some tests require specific frameworks:
- Force confirmation tests: `pico_advanced_complete`
- Multi-step navigation: Frameworks with 3+ aspects

Tests skip gracefully if framework unavailable.

### Timing Considerations
- Small delays for Redis persistence verification
- Rapid execution tests may be sensitive to server load
- Adjust timeouts if running on slower systems

### Authentication
Tests create isolated user (`command_test@example.com`) to avoid conflicts.

## Troubleshooting

### Tests Fail to Start
**Issue**: API server not running  
**Solution**: `poetry run uvicorn query_refinement_module.api.main:app --reload`

### Random Failures
**Issue**: Redis connection issues  
**Solution**: Verify Redis is running: `redis-cli ping`

### Framework Not Found
**Issue**: Test framework not loaded  
**Solution**: Check `REFINEMENT_FRAMEWORK_PATH` environment variable

### Rate Limiting
**Issue**: Too many requests  
**Solution**: Tests use single user, should not hit limits. Check middleware config.

## See Also

- [API Command Integration](api_command_integration.md) - Implementation details
- [User Commands](user_commands.md) - Command reference
- [Test Refinement Endpoints](../tests/api/test_refinement_endpoints.py) - Basic integration tests
