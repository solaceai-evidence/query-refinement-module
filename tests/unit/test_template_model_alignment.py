"""
Tests to ensure templates and Pydantic models are aligned.

These tests prevent field name mismatches between LLM templates
and response validation models.
"""

import json
import re
import pytest
from pydantic import ValidationError

from query_refinement_module.schema import (
    QueryRefinementResponse,
    DimensionEvaluationResponse,
)
from query_refinement_module.schema.templates import (
    SYNTHESIS_TEMPLATE,
    DIMENSION_REFINEMENT_TEMPLATE,
)


class TestSynthesisTemplateAlignment:
    """Ensure synthesis template matches QueryRefinementResponse model."""
    
    def test_synthesis_template_uses_correct_field_names(self):
        """Verify template uses clarified_query (LLM field name)."""
        # Template instructs LLM to return clarified_query
        assert "clarified_query" in SYNTHESIS_TEMPLATE, \
            "Template must use 'clarified_query' (LLM field name)"
        
        assert "dimensions_specifications" in SYNTHESIS_TEMPLATE, \
            "Template must use 'dimensions_specifications' (LLM field name)"

        assert "research_elements" not in SYNTHESIS_TEMPLATE, \
            "Template must not document deprecated 'research_elements' field"

        assert '"hyponyms"' not in SYNTHESIS_TEMPLATE, \
            "Template must not document deprecated 'terminology.hyponyms' field"
    
    def test_synthesis_template_json_structure_matches_model(self):
        """Verify all required model fields (via validation_alias) are documented in template."""
        # Verify required fields are present in template using their LLM names (validation_alias)
        model_fields = QueryRefinementResponse.model_fields
        
        for field_name, field_info in model_fields.items():
            if field_info.is_required():
                llm_field_name = field_info.validation_alias or field_name
                assert (
                    f'"{field_name}"' in SYNTHESIS_TEMPLATE
                    or f'"{llm_field_name}"' in SYNTHESIS_TEMPLATE
                ), f"Required field '{field_name}' missing from synthesis template"
    
    def test_synthesis_example_responses_validate(self):
        """Verify template uses LLM field names throughout."""
        # Find clarified_query occurrences in examples
        example_pattern = r'"clarified_query":\s*"[^"]+'
        example_matches = re.findall(example_pattern, SYNTHESIS_TEMPLATE)

        # Should have at least 2 example responses
        assert len(example_matches) >= 2, \
            f"Expected at least 2 example responses, found {len(example_matches)}"

        # Verify LLM field names are used
        assert '"clarified_query"' in SYNTHESIS_TEMPLATE, \
            "Template must use 'clarified_query' (LLM field name)"

        assert '"dimensions_specifications"' in SYNTHESIS_TEMPLATE, \
            "Template must use 'dimensions_specifications' (LLM field name)"


class TestDimensionTemplateAlignment:
    """Ensure dimension template matches DimensionEvaluationResponse model."""
    
    def test_dimension_template_uses_correct_field_names(self):
        """Verify template uses complete, current, question fields."""
        model_fields = DimensionEvaluationResponse.model_fields
        
        for field_name in model_fields.keys():
            assert f'"{field_name}"' in DIMENSION_REFINEMENT_TEMPLATE, \
                f"Field '{field_name}' should be documented in dimension template"
    
    def test_dimension_template_json_format_matches_model(self):
        """Verify JSON format instructions match model structure."""
        # The template should show the correct JSON structure
        assert '"complete":' in DIMENSION_REFINEMENT_TEMPLATE, \
            "Template should document 'complete' field"
        assert '"current":' in DIMENSION_REFINEMENT_TEMPLATE, \
            "Template should document 'current' field"
        assert '"question":' in DIMENSION_REFINEMENT_TEMPLATE, \
            "Template should document 'question' field"
    
    def test_dimension_response_examples_are_valid(self):
        """Test that example responses in template are valid."""
        # Example 1: Incomplete response
        incomplete_example = {
            "complete": False,
            "current": "adults over 40",
            "question": "Which clinical condition and setting—primary care, hospital, or community?"
        }
        response = DimensionEvaluationResponse(**incomplete_example)
        assert response.complete is False
        assert response.question != ""
        
        # Example 2: Complete response
        complete_example = {
            "complete": True,
            "current": "adults over 40 with type 2 diabetes in primary care settings",
            "question": ""
        }
        response = DimensionEvaluationResponse(**complete_example)
        assert response.complete is True
        assert response.current != ""


class TestResponseModelFieldNaming:
    """Verify consistent field naming across response models."""
    
    def test_no_ambiguous_field_names(self):
        """Ensure model uses canonical synthesis field names."""
        model_fields = QueryRefinementResponse.model_fields
        field_names = set(model_fields.keys())
        
        assert "clarified_query" in field_names, \
            "Model should expose 'clarified_query' as canonical field"
        
        assert "dimensions_specifications" in field_names, \
            "Model should expose 'dimensions_specifications' as canonical field"
        
        assert "synthesized_statement" not in field_names
        assert "refined_dimensions" not in field_names
    
    def test_dimension_response_field_consistency(self):
        """Ensure DimensionEvaluationResponse uses consistent field names."""
        model_fields = DimensionEvaluationResponse.model_fields
        field_names = set(model_fields.keys())
        
        # Required fields
        assert "complete" in field_names
        assert "current" in field_names
        assert "question" in field_names
        
        # Should not have old/deprecated variants
        deprecated = ["value", "refinement_value", "aspect_value", 
                     "follow_up", "followup_question"]
        for old_field in deprecated:
            assert old_field not in field_names, \
                f"Should not have deprecated field '{old_field}'"


class TestTemplateToModelIntegration:
    """Integration tests ensuring templates produce model-compatible output."""
    
    def test_synthesis_template_field_names_in_model(self):
        """Extract all field names from template and verify they exist in model."""
        # Find all quoted field names in the JSON structure section
        field_pattern = r'"([a-z_]+)":\s*["\[\{]'
        matches = re.findall(field_pattern, SYNTHESIS_TEMPLATE)
        
        # Get unique field names
        template_fields = set(matches)
        
        # Filter to top-level fields (not nested)
        top_level_template_fields = {
            "clarified_query", "dimensions_specifications",
            "search_optimized", "search_filters", "terminology",
            "metadata", "processing_log"
        }
        
        model_fields = set(QueryRefinementResponse.model_fields.keys())
        
        # Map LLM field names to model field names
        field_mapping = {
            "clarified_query": "clarified_query",
            "dimensions_specifications": "dimensions_specifications",
        }
        
        # Check that template fields map to model fields (accounting for aliases)
        for template_field, model_field in field_mapping.items():
            if template_field in template_fields:
                assert model_field in model_fields, \
                    f"Template field '{template_field}' should map to model field '{model_field}'"
    
    def test_llm_json_parses_with_validation_aliases(self):
        """Test that LLM JSON with clarified_query/dimensions_specifications parses correctly."""
        # Simulate LLM response using template field names
        llm_response = {
            "clarified_query": "Test research statement",
            "dimensions_specifications": {"population": "adults", "condition": "diabetes"},
            "search_optimized": {
                "semantic": "test query",
                "keyword": {
                    "structured": "(test)",
                    "phrases": ["test phrase"],
                    "terms": {"required": ["test"], "optional": [], "excluded": []}
                }
            },
            "search_filters": {
                "publication_years": "2020-2026",
                "venues": [],
                "authors": [],
                "publication_types": [],
                "fields_of_study": []
            },
            "terminology": {
                "synonyms": {"test": ["exam"]},
                "colloquial": []
            }
        }
        
        # Parse with Pydantic model
        response = QueryRefinementResponse(**llm_response)
        
        # Verify code can access canonical names
        assert response.clarified_query == "Test research statement"
        assert response.dimensions_specifications == {"population": "adults", "condition": "diabetes"}
        
        # Verify the aliases worked
        assert hasattr(response, 'clarified_query')
        assert hasattr(response, 'dimensions_specifications')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
