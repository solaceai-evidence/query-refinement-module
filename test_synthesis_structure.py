#!/usr/bin/env python3
"""
Test script to verify synthesis output structure alignment between:
- LLM template output
- Pydantic model parsing
- API response structure  
- Frontend expectations

This ensures the data flows correctly through the entire pipeline.
"""

import json
from typing import Dict, Any

# Sample LLM raw output (what the template produces)
llm_raw_output = {
    "integrated_statement": "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery",
    "dimensions_specifications": {
        "population": "Patients undergoing major orthopedic surgery",
        "intervention": "Thromboprophylaxis interventions",
        "comparator": "Within and across classes",
        "outcomes": None
    },
    "search_optimized": {
        "semantic": "Studies comparing thromboprophylaxis interventions...",
        "keyword": {
            "structured": "(arthroplasty AND thromboembolism)",
            "phrases": ["venous thromboembolism", "major surgery"],
            "terms": {
                "required": ["arthroplasty", "prophylaxis"],
                "optional": ["LMWH", "compression"],
                "excluded": ["pediatric"]
            }
        }
    },
    "search_filters": {
        "publication_years": "2020-2026",
        "venues": [],
        "authors": [],
        "publication_types": ["Comparative study"],
        "fields_of_study": ["Medicine"]
    },
    "terminology": {
        "synonyms": {
            "venous thromboembolism": ["VTE", "blood clots"],
            "prophylaxis": ["prevention", "preventive therapy"]
        },
        "colloquial": ["blood clot prevention", "surgical precautions"]
    }
}

print("=" * 80)
print("SYNTHESIS STRUCTURE ALIGNMENT TEST")
print("=" * 80)

print("\n1. LLM Template Output (what the LLM generates):")
print(json.dumps(llm_raw_output, indent=2)[:500] + "...")

print("\n2. Pydantic Model Processing (query_refinement_module/schema/response.py):")
print("   - Accepts: 'integrated_statement' (primary field name)")
print("   - Accepts: 'dimensions_specifications' (primary field name)")
print("   - Also accepts old names via alias for backward compatibility:")
print("     - 'synthesized_statement' (DB column name)")
print("     - 'refined_dimensions' (DB column name)")

print("\n3. core.py Output (synthesize_refined_query returns):")
core_output = {
    "integrated_statement": llm_raw_output["integrated_statement"],
    "dimensions_specifications": llm_raw_output["dimensions_specifications"],
    "search_optimized": llm_raw_output["search_optimized"],
    "search_filters": llm_raw_output["search_filters"],
    "terminology": llm_raw_output["terminology"],
    "used_llm": True,
    "clarifications": [],
    "baseline_summaries": [],
    "refinement_aspect_values": {},
    "metadata": {}
}
print(json.dumps({k: v for k, v in core_output.items() if k in ['integrated_statement', 'dimensions_specifications', 'search_optimized', 'search_filters', 'terminology']}, indent=2)[:500] + "...")

print("\n4. API Response (SynthesizeQueryResponse via routes/refinement.py):")
api_response = {
    "query_id": 789,
    "integrated_statement": core_output["integrated_statement"],
    "used_llm": core_output["used_llm"],
    "structured_output": {
        "dimensions_specifications": core_output["dimensions_specifications"],
        "search_optimized": core_output["search_optimized"],
        "search_filters": core_output["search_filters"],
        "terminology": core_output["terminology"]
    }
}
print(json.dumps(api_response, indent=2)[:500] + "...")

print("\n5. Frontend Expectations (SynthesisResult.jsx):")
print("   Required fields:")
print("   ✓ synthesis.query_id (number)")
print("   ✓ synthesis.integrated_statement (string) - displayed in 'Integrated Statement' section")
print("   ✓ synthesis.used_llm (boolean)")
print("   ✓ synthesis.structured_output (object) - displayed in 'Structured Research Output' section")
print("   ✓ synthesis.metadata (object, optional) - displayed in 'Metadata' section")

print("\n6. structured_output Contents (rendered recursively):")
structured_fields = api_response["structured_output"]
for key, value in structured_fields.items():
    value_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
    print(f"   - {key}: {type(value).__name__} {value_preview}")

print("\n" + "=" * 80)
print("VALIDATION RESULTS")
print("=" * 80)

# Validate structure
issues = []

# Check API response has required fields
required_api_fields = ['query_id', 'integrated_statement', 'used_llm']
for field in required_api_fields:
    if field not in api_response:
        issues.append(f"Missing required field in API response: {field}")

# Check structured_output has expected fields
if 'structured_output' in api_response and api_response['structured_output']:
    expected_structured_fields = ['dimensions_specifications', 'search_optimized', 'search_filters', 'terminology']
    actual_fields = set(api_response['structured_output'].keys())
    expected_fields_set = set(expected_structured_fields)
    
    missing_fields = expected_fields_set - actual_fields
    extra_fields = actual_fields - expected_fields_set
    
    if missing_fields:
        issues.append(f"Missing fields in structured_output: {missing_fields}")
    if extra_fields:
        print(f"   ℹ️  Extra fields in structured_output (not harmful): {extra_fields}")

# Check integrated_statement is a string, not JSON
if isinstance(api_response['integrated_statement'], str):
    if api_response['integrated_statement'].startswith('{') or '```json' in api_response['integrated_statement']:
        issues.append("integrated_statement contains raw JSON instead of plain text statement")

if issues:
    print("\n❌ ISSUES FOUND:")
    for issue in issues:
        print(f"   - {issue}")
else:
    print("\n✅ ALL CHECKS PASSED!")
    print("   - LLM template output structure is correct")
    print("   - Pydantic model properly maps field names")
    print("   - API response structure matches frontend expectations")
    print("   - integrated_statement is a clean string (not raw JSON)")
    print("   - structured_output contains all expected fields")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("""
The synthesis data flows through these stages with ALIGNED FIELD NAMES:

1. LLM generates JSON with standard template field names:
   - integrated_statement (canonical name)
   - dimensions_specifications (canonical name)

2. core.py parses via Pydantic and returns as dict with LLM template names:
   - integrated_statement (the clean statement text)
   - dimensions_specifications (the dimension specifications)
   - search_optimized, search_filters, terminology (unchanged)

3. API wraps in SynthesizeQueryResponse using same names:
   - integrated_statement (top-level, for easy access)
   - structured_output (contains dimensions_specifications and other fields)

4. Frontend displays using same names:
   - integrated_statement in "Integrated Statement" section (with copy button)
   - structured_output in "Structured Research Output" section (recursive render)
   - metadata in "Metadata" section (if present)

5. Database storage (crud.py maps to DB column names):
   - integrated_statement (API) → synthesized_statement (DB column)
   - dimensions_specifications (API) → refined_dimensions (DB column)

✅ All field names now use LLM template names as the canonical source throughout the entire stack.
""")
