#!/usr/bin/env python3
"""Test the /back command dimension recreation."""

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.schema import get_framework
from query_refinement_module.providers.litellm import LiteLLMProvider
from query_refinement_module.session_commands import SessionCommands

# Initialize manager
provider = LiteLLMProvider(api_key='test')
manager = QueryRefinementManager(provider)

# Create a session
framework = get_framework('pico_advanced')
session = manager.initialize_sequential('test query about COPD', framework)

print('Initial state:')
print(f'  Steps: {len(session.steps)}')
print(f'  Complete framework: {len(session._complete_framework)}')
print(f'  Framework IDs: {[a.id for a in session._complete_framework]}')

# Mark first 3 steps as complete to simulate progress
for i in range(3):
    session.steps[i].is_complete = True

print('\nAfter marking 3 complete:')
active = session.get_active_step()
print(f'  Active step: {active.refinement_aspect.id if active else None}')
print(f'  Active index: {session.steps.index(active) if active else None}')

# Now test go_back
print('\nExecuting go_back()...')
commands = SessionCommands(session)
result = commands.go_back()

print(f'\nResult:')
print(f'  Success: {result["success"]}')
if not result["success"]:
    print(f'  ERROR: {result.get("message", "No message")}')
    exit(1)

print(f'  Message: {result.get("message", "No message")}')
print(f'\nAfter go_back:')
print(f'  Steps now: {len(session.steps)}')
print(f'  Step IDs: {[s.refinement_aspect.id for s in session.steps]}')
print(f'  Step complete status: {[s.is_complete for s in session.steps]}')
print(f'  Complete framework: {len(session._complete_framework)}')

# Verify all 6 dimensions exist
if len(session.steps) == 6:
    print('\n✓ SUCCESS: All 6 dimensions present after /back')
else:
    print(f'\n✗ FAIL: Expected 6 dimensions, got {len(session.steps)}')
    exit(1)

# Verify the previous dimension was cleared
if not session.steps[1].is_complete:
    print('✓ SUCCESS: Previous dimension was cleared')
else:
    print('✗ FAIL: Previous dimension still marked complete')
    exit(1)

print('\n✓ All tests passed!')
