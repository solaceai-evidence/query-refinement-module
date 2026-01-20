"""
Tests for dynamic value field system with all supported types.

Tests cover:
- Schema validation for all 6 value field types
- refinement_aspect_value extraction for complex types
- Dependency context with type information
- Incremental synthesis workflow
- Type conversion and formatting
"""

import json
import pytest
from query_refinement_module.schema.model import RefinementAspect
from query_refinement_module.core import QueryAspectRefiner, QueryRefinementSession


# ============================================================================
# Test Fixtures
# ============================================================================

def make_aspect(
    aspect_id="test",
    name="Test Aspect",
    value_field_type="string",
    value_field_description=None
):
    """Create a minimal RefinementAspect for testing."""
    return RefinementAspect(
        id=aspect_id,
        aspect_name=name,
        aspect_description="Test description",
        refinement_instructions="Review this query: {query}",
        value_field_type=value_field_type,
        value_field_description=value_field_description
    )






# ============================================================================
# Dynamic Field Schema Tests
# ============================================================================

def test_complete_schema_includes_dynamic_field():
    """_get_complete_schema_fields should include dynamic field with aspect.id as name."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    fields = aspect._get_complete_schema_fields()
    
    assert "population" in fields
    assert fields["population"] == "string"


def test_complete_schema_includes_all_base_fields():
    """Schema should include all base fields plus dynamic field."""
    aspect = make_aspect(aspect_id="intervention")
    fields = aspect._get_complete_schema_fields()
    
    assert "is_complete" in fields
    assert "reasoning" in fields
    assert "refinement_aspect_value" in fields
    assert "next_question" in fields
    assert "intervention" in fields  # dynamic field


def test_field_descriptions_include_synthesis_instructions():
    """Field descriptions should auto-generate synthesis instructions."""
    aspect = make_aspect(
        aspect_id="outcome",
        value_field_type="object",
        value_field_description="The primary outcome measure"
    )
    descriptions = aspect._get_complete_field_descriptions()
    
    assert "outcome" in descriptions
    desc = descriptions["outcome"]
    assert "The primary outcome measure" in desc
    assert "SYNTHESIS REQUIRED" in desc
    assert "Update this field incrementally" in desc


# ============================================================================
# refinement_aspect_value Extraction Tests
# ============================================================================

def test_refinement_aspect_value_extracts_string():
    """Should extract string value from dynamic field."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "population": "Adults aged 18-65 with Type 2 diabetes"
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert value == "Adults aged 18-65 with Type 2 diabetes"
    assert isinstance(value, str)


def test_refinement_aspect_value_extracts_object():
    """Should extract object value from dynamic field as dict."""
    aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "intervention": {
            "name": "metformin",
            "dosage": "500mg twice daily",
            "duration": "12 weeks"
        }
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert isinstance(value, dict)
    assert value["name"] == "metformin"
    assert value["dosage"] == "500mg twice daily"
    assert value["duration"] == "12 weeks"


def test_refinement_aspect_value_extracts_array():
    """Should extract array value from dynamic field as list."""
    aspect = make_aspect(aspect_id="outcomes", value_field_type="array")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "outcomes": [
            "HbA1c via blood test at baseline",
            "Weight at 12 weeks",
            "Quality of life score"
        ]
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert isinstance(value, list)
    assert len(value) == 3
    assert "HbA1c via blood test at baseline" in value


def test_refinement_aspect_value_extracts_boolean():
    """Should extract boolean value from dynamic field."""
    aspect = make_aspect(aspect_id="blinded", value_field_type="boolean")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "blinded": True
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert value is True
    assert isinstance(value, bool)


def test_refinement_aspect_value_extracts_integer():
    """Should extract integer value from dynamic field."""
    aspect = make_aspect(aspect_id="sample_size", value_field_type="integer")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "sample_size": 500
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert value == 500
    assert isinstance(value, int)


def test_refinement_aspect_value_extracts_float():
    """Should extract float value from dynamic field."""
    aspect = make_aspect(aspect_id="effect_size", value_field_type="float")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "effect_size": 0.75
    })
    refiner.add_follow_up("Q", response)
    
    value = refiner.refinement_aspect_value
    assert value == 0.75
    assert isinstance(value, float)


def test_refinement_aspect_value_iterates_backwards():
    """Should get most recent value when multiple responses exist."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    # Add multiple responses
    refiner.add_follow_up("Q1", json.dumps({
        "is_complete": False,
        "reasoning": "Need more",
        "next_question": "Age?",
        "population": "Adults"
    }))
    refiner.add_follow_up("Q2", json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "population": "Adults aged 18-65 with diabetes"
    }))
    
    value = refiner.refinement_aspect_value
    assert value == "Adults aged 18-65 with diabetes"


def test_refinement_aspect_value_stores_directly():
    """Should store value directly when set."""
    aspect = make_aspect(aspect_id="population")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    refiner.refinement_aspect_value = "Direct value"
    
    value = refiner.refinement_aspect_value
    assert value == "Direct value"


def test_refinement_aspect_value_handles_plain_text_response():
    """Plain text responses should be stored in refinement_aspect_value (overwrites previous)."""
    aspect = make_aspect(aspect_id="population")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    refiner.refinement_aspect_value = "Initial"
    
    refiner.add_follow_up("Q", "Just plain text response")
    
    value = refiner.refinement_aspect_value
    assert value == "Just plain text response"  # Updated with latest response


# ============================================================================
# final_response Property Tests
# ============================================================================

def test_final_response_returns_string_for_simple_types():
    """final_response should return string value for string types."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "population": "Adults aged 18-65"
    })
    refiner.add_follow_up("Q", response)
    
    assert refiner.refinement_aspect_value_as_str == "Adults aged 18-65"


def test_final_response_converts_object_to_json_string():
    """final_response should convert dict to JSON string."""
    aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "intervention": {"name": "metformin", "dosage": "500mg"}
    })
    refiner.add_follow_up("Q", response)
    
    final = refiner.refinement_aspect_value_as_str
    assert isinstance(final, str)
    parsed = json.loads(final)
    assert parsed["name"] == "metformin"


def test_final_response_converts_array_to_json_string():
    """final_response should convert list to JSON string."""
    aspect = make_aspect(aspect_id="outcomes", value_field_type="array")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    response = json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "outcomes": ["HbA1c", "Weight"]
    })
    refiner.add_follow_up("Q", response)
    
    final = refiner.refinement_aspect_value_as_str
    assert isinstance(final, str)
    parsed = json.loads(final)
    assert "HbA1c" in parsed


# ============================================================================
# Dependency Context Tests
# ============================================================================

def test_dependency_context_includes_type_field():
    """Dependency context should include type information."""
    session = QueryRefinementSession(original_query="test query")
    
    pop_aspect = make_aspect(aspect_id="population", value_field_type="string")
    int_aspect = make_aspect(
        aspect_id="intervention",
        value_field_type="object",
        value_field_description="Intervention details"
    )
    int_aspect.depends_on = ["population"]
    
    pop_step = session.add_step(pop_aspect)
    pop_step.refinement_aspect_value = "Adults aged 18-65"
    
    session.add_step(int_aspect)
    
    context = session.get_dependency_context("intervention")
    
    assert "population" in context
    assert context["population"]["type"] == "string"
    assert context["population"]["value"] == "Adults aged 18-65"


def test_dependency_context_formats_complex_types():
    """Dependency context should pretty-print objects and arrays."""
    session = QueryRefinementSession(original_query="test query")
    
    int_aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    out_aspect = make_aspect(aspect_id="outcome", value_field_type="string")
    out_aspect.depends_on = ["intervention"]
    
    int_step = session.add_step(int_aspect)
    int_step.refinement_aspect_value = json.dumps({"name": "metformin", "dosage": "500mg"})
    
    session.add_step(out_aspect)
    
    context = session.get_dependency_context("outcome")
    
    assert "intervention" in context
    value = context["intervention"]["value"]
    # Should be pretty-printed
    assert "\n" in value  # Has line breaks from indent
    assert "name" in value
    assert "metformin" in value


def test_dependency_context_with_array_type():
    """Dependency context should handle array types."""
    session = QueryRefinementSession(original_query="test query")
    
    out_aspect = make_aspect(aspect_id="outcomes", value_field_type="array")
    cmp_aspect = make_aspect(aspect_id="comparison", value_field_type="string")
    cmp_aspect.depends_on = ["outcomes"]
    
    out_step = session.add_step(out_aspect)
    out_step.refinement_aspect_value = json.dumps(["HbA1c", "Weight", "QoL"])
    
    session.add_step(cmp_aspect)
    
    context = session.get_dependency_context("comparison")
    
    assert "outcomes" in context
    assert context["outcomes"]["type"] == "array"
    value = context["outcomes"]["value"]
    assert "HbA1c" in value


# ============================================================================
# Validation Tests
# ============================================================================

def test_validate_response_requires_dynamic_field():
    """validate_response should require refinement_aspect_value when is_complete=True."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    
    # Missing refinement_aspect_value when is_complete=True
    response = {
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": None
    }
    
    is_valid, error_msg = aspect.validate_response(response)
    assert not is_valid
    assert "refinement_aspect_value" in error_msg


def test_validate_response_accepts_dynamic_field():
    """validate_response should accept response with refinement_aspect_value."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    
    response = {
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": None,
        "refinement_aspect_value": "Adults aged 18-65"
    }
    
    is_valid, error_msg = aspect.validate_response(response)
    assert is_valid
    assert error_msg is None


def test_validate_response_with_object_type():
    """validate_response should accept object values in refinement_aspect_value."""
    aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    
    response = {
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": None,
        "refinement_aspect_value": "{\"name\": \"metformin\"}"
    }
    
    is_valid, error_msg = aspect.validate_response(response)
    assert is_valid


def test_validate_response_with_array_type():
    """validate_response should accept array values in refinement_aspect_value."""
    aspect = make_aspect(aspect_id="outcomes", value_field_type="array")
    
    response = {
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": None,
        "refinement_aspect_value": "[\"HbA1c\", \"Weight\"]"
    }
    
    is_valid, error_msg = aspect.validate_response(response)
    assert is_valid


# ============================================================================
# Incremental Synthesis Tests
# ============================================================================

def test_incremental_synthesis_string_builds_up():
    """String values should build incrementally across responses."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    # Response 1: Partial info
    refiner.add_follow_up("Q1", json.dumps({
        "is_complete": False,
        "reasoning": "Need age",
        "next_question": "What age?",
        "population": "Adults"
    }))
    assert refiner.refinement_aspect_value == "Adults"
    
    # Response 2: More info
    refiner.add_follow_up("Q2", json.dumps({
        "is_complete": False,
        "reasoning": "Need condition",
        "next_question": "What condition?",
        "population": "Adults aged 18-65"
    }))
    assert refiner.refinement_aspect_value == "Adults aged 18-65"
    
    # Response 3: Complete
    refiner.add_follow_up("Q3", json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "population": "Adults aged 18-65 with Type 2 diabetes"
    }))
    assert refiner.refinement_aspect_value == "Adults aged 18-65 with Type 2 diabetes"


def test_incremental_synthesis_object_adds_fields():
    """Object values should add fields incrementally."""
    aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    # Response 1: Just name
    refiner.add_follow_up("Q1", json.dumps({
        "is_complete": False,
        "reasoning": "Need dosage",
        "next_question": "What dosage?",
        "intervention": {"name": "metformin"}
    }))
    value = refiner.refinement_aspect_value
    assert value["name"] == "metformin"
    assert "dosage" not in value
    
    # Response 2: Add dosage
    refiner.add_follow_up("Q2", json.dumps({
        "is_complete": False,
        "reasoning": "Need duration",
        "next_question": "How long?",
        "intervention": {"name": "metformin", "dosage": "500mg twice daily"}
    }))
    value = refiner.refinement_aspect_value
    assert value["name"] == "metformin"
    assert value["dosage"] == "500mg twice daily"
    
    # Response 3: Complete
    refiner.add_follow_up("Q3", json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "intervention": {
            "name": "metformin",
            "dosage": "500mg twice daily",
            "duration": "12 weeks"
        }
    }))
    value = refiner.refinement_aspect_value
    assert len(value) == 3
    assert value["duration"] == "12 weeks"


def test_incremental_synthesis_array_adds_items():
    """Array values should add items incrementally."""
    aspect = make_aspect(aspect_id="outcomes", value_field_type="array")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    # Response 1: One item
    refiner.add_follow_up("Q1", json.dumps({
        "is_complete": False,
        "reasoning": "Need more",
        "next_question": "Other outcomes?",
        "outcomes": ["HbA1c via blood test"]
    }))
    value = refiner.refinement_aspect_value
    assert len(value) == 1
    
    # Response 2: More items
    refiner.add_follow_up("Q2", json.dumps({
        "is_complete": True,
        "reasoning": "Complete",
        "next_question": "",
        "outcomes": ["HbA1c via blood test", "Weight at 12 weeks", "QoL score"]
    }))
    value = refiner.refinement_aspect_value
    assert len(value) == 3


# ============================================================================
# Format Follow-up Prompt Tests
# ============================================================================

def test_follow_up_prompt_shows_current_value_string():
    """Follow-up prompt should show current synthesized value for string."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    refiner.add_follow_up("Q", json.dumps({
        "is_complete": False,
        "reasoning": "Need more",
        "next_question": "Age?",
        "population": "Adults"
    }))
    
    prompt = refiner.format_follow_up_prompt_template("original query")
    
    assert "CURRENT VALUE FOR 'population': Adults" in prompt


def test_follow_up_prompt_shows_current_value_object():
    """Follow-up prompt should pretty-print object values."""
    aspect = make_aspect(aspect_id="intervention", value_field_type="object")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    refiner.add_follow_up("Q", json.dumps({
        "is_complete": False,
        "reasoning": "Need more",
        "next_question": "Dosage?",
        "intervention": {"name": "metformin"}
    }))
    
    prompt = refiner.format_follow_up_prompt_template("original query")
    
    assert "CURRENT VALUE FOR 'intervention':" in prompt
    assert "metformin" in prompt
    assert "{" in prompt  # JSON formatting


def test_follow_up_prompt_references_aspect_id_field():
    """Follow-up prompt should reference aspect.id field not final_value."""
    aspect = make_aspect(aspect_id="population", value_field_type="string")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    prompt = refiner.format_follow_up_prompt_template("original query")
    
    assert "'population' field" in prompt
    assert "GOOD population:" in prompt
    assert "BAD population:" in prompt
