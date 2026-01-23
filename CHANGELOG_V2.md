# Query Refinement Module v2.0.0 - Breaking Changes

## Overview
Version 2.0.0 is a major release that removes all deprecated code and simplifies the architecture for production use.

## 🔴 BREAKING CHANGES

### 1. Removed Deprecated Analyzer Module
**Deleted Files:**
- `query_refinement_module/analyzers.py` (327 lines)
- `tests/unit/test_analyzers.py` (50+ lines)

**Removed Classes:**
- `LLMQueryAnalyzer` - No longer available
- `AspectAnalysisResult` - Removed from interfaces

**Migration:** Use `initialize_sequential()` instead of `initialize()` for all new code.

### 2. Removed QueryAnalyzerInterface
**Location:** `query_refinement_module/interfaces.py`

**Removed:**
- `QueryAnalyzerInterface` abstract class
- `AspectAnalysisResult` dataclass
- All related analyzer methods

**Impact:** 
- No upfront analysis of aspects
- All refinement is on-demand
- Simpler, faster initialization

### 3. Removed Deprecated Methods from Core

**Removed from `QueryRefinementManager`:**
- `async def initialize()` - Use `initialize_sequential()` instead
- `def _analyze_aspects_sequential()` - Internal analyzer helper
- `def _populate_session_steps()` - Internal analyzer helper
- `def _handle_failed_analysis()` - Internal analyzer helper
- `def _log_session_summary()` - Internal analyzer helper

**Simplified:**
- `def _maybe_autocomplete_dependent_step()` - No longer calls analyzer

### 4. Updated Constructor Signature

**Old (v1.x):**
```python
QueryRefinementManager(
    llm_provider=provider,
    query_analyzer=analyzer,  # REMOVED
    tracing_provider=tracer
)
```

**New (v2.0):**
```python
QueryRefinementManager(
    llm_provider=provider,
    tracing_provider=tracer  # query_analyzer removed
)
```

### 5. Module Exports Cleanup

**Removed from `__init__.py` exports:**
- `LLMQueryAnalyzer`

**Removed from `interfaces.py` exports:**
- `QueryAnalyzerInterface`
- `AspectAnalysisResult`

## ✅ Migration Guide

### Before (v1.x):
```python
from query_refinement_module import (
    QueryRefinementManager,
    LLMQueryAnalyzer,  # REMOVED
    LiteLLMProvider
)

provider = LiteLLMProvider(default_model="gpt-4o-mini")
analyzer = LLMQueryAnalyzer(provider)  # REMOVED

manager = QueryRefinementManager(
    llm_provider=provider,
    query_analyzer=analyzer  # REMOVED
)

# Upfront analysis of all aspects
session = await manager.initialize(query, framework)  # DEPRECATED
```

### After (v2.0):
```python
from query_refinement_module import (
    QueryRefinementManager,
    LiteLLMProvider
)

provider = LiteLLMProvider(default_model="gpt-4o-mini")

manager = QueryRefinementManager(
    llm_provider=provider
    # No analyzer needed
)

# On-demand refinement - no upfront analysis
session = manager.initialize_sequential(query, framework)  # NEW
```

## 📊 Code Reduction

**Total Lines Removed:** ~667 lines

| Component | Lines Removed |
|-----------|---------------|
| analyzers.py (deleted) | 327 |
| test_analyzers.py (deleted) | 50 |
| interfaces.py (QueryAnalyzerInterface) | 100 |
| core.py (initialize + helpers) | 190 |

**File Size Reductions:**
- `core.py`: 2,426 → 2,164 lines (-11%)
- `interfaces.py`: 591 → 494 lines (-16%)

## 🎯 Benefits

1. **Simpler Architecture:** No upfront analysis overhead
2. **Faster Initialization:** Instant session creation
3. **Lower LLM Costs:** Only refine aspects as needed
4. **Cleaner Code:** 667 lines of complexity removed
5. **Better UX:** Progressive refinement feels more responsive

## ⚠️ Test Suite Updates Required

Tests using deprecated `initialize()` method need updates:
- `tests/unit/test_core.py` - Uses `initialize()` with analyzer
- `tests/unit/test_manager.py` - Tests analyzer integration
- `tests/unit/test_enhanced_synthesis.py` - Uses StubQueryAnalyzer
- `tests/unit/test_followup_loop.py` - Uses DummyAnalyzer

**Recommendation:** Update these tests to use `initialize_sequential()` or mark as legacy tests.

## 🚀 What's Next

With v2.0 cleanup complete, the codebase is ready for:
- Phase 2: Refactor core.py (extract data classes, commands)
- Phase 3: Split large API route files
- Phase 4: Organize providers into package structure
- Phase 5: Remove deprecated schema fields

## Version Info

- **Previous Version:** 0.3.0
- **New Version:** 2.0.0
- **Release Date:** 2026-01-23
- **Breaking Changes:** Yes (major version bump)
