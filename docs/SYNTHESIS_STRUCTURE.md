# Synthesis Output Structure Reference

## Overview
This documents the complete data flow for synthesis output from LLM → API → Frontend.

**IMPORTANT:** All components now use consistent LLM template field names throughout the entire system:
- `integrated_statement` (the refined query statement)- `dimensions_specifications` (the dimension specifications)

## Complete Flow

### 1️⃣ LLM Template Output
**File:** `query_refinement_module/schema/templates/synthesis.py`

The LLM generates JSON with these field names (canonical names):
```json
{
  "integrated_statement": "Refined research statement...",
  "dimensions_specifications": {
    "population": "value",
    "intervention": "value",
    ...
  },
  "search_optimized": {
    "semantic": "...",
    "keyword": {...}
  },
  "search_filters": {...},
  "terminology": {...}
}
```

### 2️⃣ Pydantic Model Processing
**File:** `query_refinement_module/schema/response.py`

The `QueryRefinementResponse` model uses LLM template names as primary field names:

- `integrated_statement` (canonical, from LLM)
- `dimensions_specifications` (canonical, from LLM)

For backward compatibility with database column names, it also accepts via `alias`:
- `synthesized_statement` (database column name)
- `refined_dimensions` (database column name)

### 3️⃣ core.py Output
**File:** `query_refinement_module/core.py`

The `synthesize_refined_query()` method returns:
```python
{
    "integrated_statement": str,              # The clean statement text (LLM field name)
    "used_llm": bool,
    "dimensions_specifications": dict,         # The dimension specifications (LLM field name)
    "search_optimized": dict,
    "search_filters": dict,
    "terminology": dict,
    "clarifications": list,
    "baseline_summaries": list,
    "refinement_aspect_values": dict,
    "metadata": dict
}
```

### 4️⃣ API Response
**File:** `query_refinement_module/api/routes/refinement.py`

The `/api/refinement/synthesize` endpoint returns `SynthesizeQueryResponse`:
```json
{
  "query_id": 789,
  "integrated_statement": "Clean statement text here",
  "used_llm": true,
  "structured_output": {
    "dimensions_specifications": {...},
    "search_optimized": {...},
    "search_filters": {...},
    "terminology": {...}
  }
}
```

### 5️⃣ Frontend Display
**File:** `frontend/src/components/SynthesisResult.jsx`

The component expects:
- `synthesis.integrated_statement` (string) → Displayed in "Integrated Statement" section
- `synthesis.structured_output` (object) → Displayed in "Structured Research Output" section
- `synthesis.metadata` (object, optional) → Displayed in "Metadata" section

## Field Mappings

| LLM Template                | Pydantic Model              | core.py Output             | API Response                            | Frontend Access                                               |
| --------------------------- | --------------------------- | -------------------------- | --------------------------------------- | ------------------------------------------------------------- |
| `integrated_statement`      | `integrated_statement`      | `integrated_statement`     | `integrated_statement`                  | `synthesis.integrated_statement`                              |
| `dimensions_specifications` | `dimensions_specifications` | `dimensions_specifications` | `structured_output.dimensions_specifications` | `synthesis.structured_output.dimensions_specifications`       |
| `search_optimized`          | `search_optimized`          | `search_optimized`         | `structured_output.search_optimized`    | `synthesis.structured_output.search_optimized`                |
| `search_filters`            | `search_filters`            | `search_filters`           | `structured_output.search_filters`      | `synthesis.structured_output.search_filters`                  |
| `terminology`               | `terminology`               | `terminology`              | `structured_output.terminology`         | `synthesis.structured_output.terminology`                     |

### Database Mapping (persistence layer only)
For database persistence only, crud.py maps:
- `integrated_statement` (API) → `synthesized_statement` (DB column)
- `dimensions_specifications` (API) → `refined_dimensions` (DB column)

## Recent Changes (Feb 2026)

### ✅ Complete Field Name Alignment
**Status:** COMPLETED ✅

**Changes Made:**
1. **Backend:** Changed all code to use LLM template field names as canonical:
   - `core.py`: Returns `integrated_statement` instead of `refined_query`
   - `core.py`: Returns `dimensions_specifications` instead of `detail_values`
   - `refinement.py`: API response uses `integrated_statement` field
   - `refinement.py`: API `structured_output` uses `dimensions_specifications`
   - `crud.py`: Maps API names to database columns (integrated_statement → synthesized_statement, dimensions_specifications → refined_dimensions)

2. **Frontend:** Updated all components to use aligned field names:
   - `SynthesisResult.jsx`: Expects `synthesis.integrated_statement`
   - `Refinement.jsx`: Uses `integrated_statement` in validation and parsing
   - `api.d.ts`: TypeScript interfaces updated with `integrated_statement` and `dimensions_specifications`

3. **Database:** Retains original column names for backward compatibility:
   - `synthesized_statement` (stores integrated_statement)
   - `refined_dimensions` (stores dimensions_specifications)
   - `crud.py` handles the mapping transparently

**Result:** Complete naming consistency across the entire stack - LLM → Pydantic → core.py → API → Frontend all use the same field names.

### ✅ Previous Fixes

**Issue 1: SynthesisResult component not rendering**
- **Problem:** Component nested inside wrong conditional block
- **Fix:** Moved rendering outside stage === 'refinement' block

**Issue 2: Inconsistent field name in API fallback parser**
- **Problem:** Parser using 'dimensions' instead of consistent name
- **Fix:** Updated to use LLM template names consistently

## Testing

Run the validation script:
```bash
python test_synthesis_structure.py
```

Expected output: `✅ ALL CHECKS PASSED!`

## Summary

✅ **LLM template output** uses descriptive field names (`integrated_statement`, `dimensions_specifications`)  
✅ **Pydantic model** handles the mapping via `validation_alias`  
✅ **API response** uses consistent field names (`detail_values`, `search_optimized`, etc.)  
✅ **Frontend** displays the structure recursively, so it works with any JSON schema  
✅ **All naming is now consistent** throughout the pipeline
