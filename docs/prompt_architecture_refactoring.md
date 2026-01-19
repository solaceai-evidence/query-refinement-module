# Prompt Generation Architecture Refactoring

## Overview
Moved all prompt generation logic from standalone module to the `RefinementAspect` domain class, improving code cohesion and following single responsibility principles.

## Changes Made

### 1. **Deleted File**
- **File:** `query_refinement_module/prompt/unified_analysis_prompt.py`
- **Reason:** All logic moved to `RefinementAspect` class

### 2. **Updated: query_refinement_module/schema/model.py**

#### Added Class Constant (Line ~236)
```python
UNIFIED_ANALYSIS_PROMPT = """
[50-line template with placeholders for:
- aspect_name, aspect_description
- original_query
- conversation_section
- dependency_section  
- refinement_instructions
- examples_section]
"""
```

#### Added Public Method
```python
def build_unified_prompt(
    self,
    original_query: str,
    follow_up_history: List[Dict[str, str]],
    dependency_context: Dict[str, Dict[str, Any]],
    mode: Literal["initial", "followup"]
) -> str:
    """
    Orchestrates all sections and returns complete prompt.
    Called by core.py.
    """
```

#### Added Private Helper Methods
```python
def _build_conversation_section(
    self,
    follow_up_history: List[Dict[str, str]],
    mode: str
) -> str:
    """Formats Q&A history for follow-up prompts."""

def _build_dependency_section(
    self,
    dependency_context: Dict[str, Dict[str, Any]]
) -> str:
    """Shows completed aspects with dependency markers."""

def _build_refinement_instructions_section(
    self,
    original_query: str
) -> str:
    """Wraps aspect.get_refinement_instructions_prompt()."""

def _build_examples_section_for_prompt(self) -> str:
    """Formats examples by category for prompt inclusion."""
```

### 3. **Updated: query_refinement_module/core.py**

#### Removed Imports (Lines 70-78)
```python
# REMOVED:
from query_refinement_module.prompt.unified_analysis_prompt import (
    UNIFIED_ANALYSIS_PROMPT,
    build_conversation_section,
    build_dependency_section,
    build_refinement_instructions,
    build_examples_section,
)
```

#### Simplified _build_unified_prompt Method (Lines 1270-1310)
**Before (~40 lines):**
```python
def _build_unified_prompt(...):
    # Manual assembly of all sections
    conversation_section = build_conversation_section(...)
    dependency_section = build_dependency_section(...)
    refinement_instructions = build_refinement_instructions(...)
    examples_section = build_examples_section(...)
    
    return UNIFIED_ANALYSIS_PROMPT.format(
        aspect_name=aspect.aspect_name,
        aspect_description=aspect.aspect_description,
        original_query=original_query,
        conversation_section=conversation_section,
        dependency_section=dependency_section,
        refinement_instructions=refinement_instructions,
        examples_section=examples_section
    )
```

**After (~10 lines):**
```python
def _build_unified_prompt(...) -> str:
    """Build unified prompt using aspect's method."""
    return aspect.build_unified_prompt(
        original_query=original_query,
        follow_up_history=follow_up_history,
        dependency_context=dependency_context,
        mode=mode
    )
```

### 4. **Updated: tests/unit/test_unified_prompt.py**

#### Changes:
- Removed imports from deleted module
- Added pytest fixture for `sample_aspect`
- Updated all test functions to call methods on `RefinementAspect` instances:
  - `aspect._build_conversation_section(...)`
  - `aspect._build_dependency_section(...)`
  - `aspect._build_refinement_instructions_section(...)`
  - `aspect._build_examples_section_for_prompt()`
  - `aspect.build_unified_prompt(...)`

#### Test Results:
- **All 12 tests passing** (test_unified_prompt.py)
- **All 51 tests passing** (critical test suite)

## Architecture Benefits

### Before
```
prompt/unified_analysis_prompt.py
  ├── UNIFIED_ANALYSIS_PROMPT (template)
  └── 4 standalone functions (business logic)

schema/model.py
  └── RefinementAspect (data model only)

core.py
  ├── Manual import of all helpers
  └── Manual assembly in _build_unified_prompt (~40 lines)
```

### After
```
schema/model.py
  └── RefinementAspect (data + behavior)
      ├── UNIFIED_ANALYSIS_PROMPT (class constant)
      ├── build_unified_prompt() (public interface)
      └── 4 private methods (encapsulated logic)

core.py
  └── Simple call: aspect.build_unified_prompt() (~10 lines)

prompt/ (can be simplified or removed)
```

## Key Improvements

1. **Encapsulation**: All prompt-related logic lives with the domain object
2. **Cohesion**: `RefinementAspect` now owns both data and prompt generation behavior
3. **Single Responsibility**: Prompt folder can contain only template strings/constants
4. **Simplified Usage**: One-line method call instead of manual assembly
5. **Maintainability**: Changes to prompt generation only affect one class
6. **Testability**: All logic testable through aspect methods

## Validation

✅ **Syntax Check**: All modified files compile  
✅ **Unit Tests**: 51/51 passing (100%)  
✅ **Integration Test**: CLI execution verified with `pico_advanced` framework  
✅ **Test Coverage**: test_unified_prompt.py fully updated and passing  

## Migration Notes

- No API changes - all external interfaces remain the same
- No database migrations required
- No frontend changes needed
- Core functionality fully validated through existing test suite
