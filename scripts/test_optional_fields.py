#!/usr/bin/env python3
"""
Test script to verify optional fields work correctly in QueryRefinementResponse.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from query_refinement_module.schema.response import QueryRefinementResponse

print("=" * 70)
print("TESTING OPTIONAL FIELDS IN QueryRefinementResponse")
print("=" * 70)

# Test 1: Minimal payload (no optional fields)
print("\n1. Testing minimal payload (optional fields omitted)...")
try:
    minimal_response = QueryRefinementResponse(**{
        "synthesized_statement": "diabetes in adults",
        "refined_dimensions": {"population": "adults"},
        "search_optimized": {
            "semantic": "diabetes in adults",
            "keyword": {
                "structured": "diabetes AND adults",
                "phrases": ["diabetes", "adults"],
                "terms": {"required": ["diabetes"], "optional": [], "excluded": []}
            }
            # grey_literature omitted
        },
        "search_filters": {
            "publication_years": "",
            "venues": [],
            "authors": [],
            "publication_types": [],
            "fields_of_study": []
        },
        "terminology": {
            # primary_terms omitted
            "synonyms": {"diabetes": ["T2DM"]},
            # domain_specific omitted
            "colloquial": []
        }
        # metadata omitted
        # processing_log omitted
    })
    
    print("   ✓ Successfully created with minimal fields")
    print(f"   - grey_literature: {minimal_response.search_optimized.grey_literature}")
    print(f"   - primary_terms: {minimal_response.terminology.primary_terms}")
    print(f"   - domain_specific: {minimal_response.terminology.domain_specific}")
    print(f"   - metadata: {minimal_response.metadata}")
    print(f"   - processing_log: {minimal_response.processing_log}")
    
except Exception as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 2: Full payload (with all optional fields)
print("\n2. Testing full payload (all optional fields included)...")
try:
    full_response = QueryRefinementResponse(**{
        "synthesized_statement": "diabetes in adults",
        "refined_dimensions": {"population": "adults"},
        "search_optimized": {
            "semantic": "diabetes in adults",
            "keyword": {
                "structured": "diabetes AND adults",
                "phrases": ["diabetes", "adults"],
                "terms": {"required": ["diabetes"], "optional": [], "excluded": []}
            },
            "grey_literature": {
                "broad_concepts": ["diabetes management"],
                "organizational_terms": ["WHO", "ADA"],
                "geographic_variants": ["US", "UK"]
            }
        },
        "search_filters": {
            "publication_years": "2020-2026",
            "venues": ["Diabetes Care"],
            "authors": [],
            "publication_types": ["Systematic review"],
            "fields_of_study": ["Medicine"]
        },
        "terminology": {
            "primary_terms": ["diabetes", "glycemic control"],
            "synonyms": {"diabetes": ["T2DM", "type 2 diabetes"]},
            "domain_specific": ["HbA1c", "fasting glucose"],
            "colloquial": ["blood sugar"]
        },
        "metadata": {
            "temporal": "recent",
            "geographic": None,
            "source_types": ["academic"],
            "other": {}
        },
        "processing_log": {
            "preserved": ["diabetes"],
            "normalized": ["T2DM"],
            "integrated": ["adults"],
            "expanded": ["glycemic control"]
        }
    })
    
    print("   ✓ Successfully created with all fields")
    print(f"   - grey_literature: {full_response.search_optimized.grey_literature.broad_concepts}")
    print(f"   - primary_terms: {full_response.terminology.primary_terms}")
    print(f"   - domain_specific: {full_response.terminology.domain_specific}")
    print(f"   - metadata: {list(full_response.metadata.keys())}")
    print(f"   - processing_log: {list(full_response.processing_log.keys())}")
    
except Exception as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

# Test 3: Conversion to dict (important for API responses)
print("\n3. Testing model_dump() with optional fields...")
try:
    response_dict = minimal_response.model_dump()
    print("   ✓ Successfully converted to dict")
    print(f"   - grey_literature in dict: {'grey_literature' in response_dict.get('search_optimized', {})}")
    print(f"   - Value: {response_dict['search_optimized'].get('grey_literature')}")
    
except Exception as e:
    print(f"   ✗ Failed: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ ALL OPTIONAL FIELD TESTS PASSED")
print("=" * 70)
print("\nSummary:")
print("  • grey_literature is now optional in search_optimized")
print("  • primary_terms is now optional in terminology")
print("  • domain_specific is now optional in terminology")
print("  • metadata is now optional in QueryRefinementResponse")
print("  • processing_log is now optional in QueryRefinementResponse")
print("\nThe Pydantic model accepts payloads with or without these fields.")
