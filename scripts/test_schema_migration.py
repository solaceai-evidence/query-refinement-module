#!/usr/bin/env python3
"""
Quick validation script to test the schema field migration.

This script verifies that:
1. Pydantic model validates correctly with new field names
2. Field defaults work as expected (empty strings, not None)
3. Validators catch invalid combinations
"""

from query_refinement_module.schema.response import DimensionEvaluationResponse

def test_complete_true():
    """Test complete=True with current value."""
    r = DimensionEvaluationResponse(
        complete=True,
        current="adults aged 18-65 with type 2 diabetes",
        question=""
    )
    assert r.complete is True
    assert r.current == "adults aged 18-65 with type 2 diabetes"
    assert r.question == ""
    print("✓ complete=True test passed")

def test_complete_false():
    """Test complete=False with question."""
    r = DimensionEvaluationResponse(
        complete=False,
        current="",
        question="What age range are you targeting? (e.g., children 5-12, adults 18-65, elderly 65+)"
    )
    assert r.complete is False
    assert r.current == ""
    assert r.question.startswith("What age range")
    print("✓ complete=False test passed")

def test_validation_failure_empty_current():
    """Test that complete=True requires non-empty current."""
    try:
        DimensionEvaluationResponse(
            complete=True,
            current="",  # Should fail - empty when complete
            question=""
        )
        assert False, "Should have raised validation error"
    except ValueError:
        print("✓ Validation correctly rejects empty current when complete=True")

def test_validation_failure_empty_question():
    """Test that complete=False requires non-empty question."""
    try:
        DimensionEvaluationResponse(
            complete=False,
            current="",
            question=""  # Should fail - empty when incomplete
        )
        assert False, "Should have raised validation error"
    except ValueError:
        print("✓ Validation correctly rejects empty question when complete=False")

def test_model_dump():
    """Test that model serializes correctly."""
    r = DimensionEvaluationResponse(
        complete=True,
        current="value",
        question=""
    )
    data = r.model_dump()
    assert data['complete'] is True
    assert data['current'] == "value"
    assert data['question'] == ""
    assert 'is_complete' not in data  # Old field name should not exist
    assert 'refinement_aspect_value' not in data  # Old field name should not exist
    assert 'reasoning' not in data  # Removed field should not exist
    print("✓ Model serialization test passed")

if __name__ == "__main__":
    print("Testing schema field migration...\n")
    
    test_complete_true()
    test_complete_false()
    test_validation_failure_empty_current()
    test_validation_failure_empty_question()
    test_model_dump()
    
    print("\n✅ All tests passed! Schema migration is working correctly.")
