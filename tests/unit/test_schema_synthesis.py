"""
Tests for SynthesisPromptBuilder.
"""

import pytest

from query_refinement_module.schema.synthesis import (
    SynthesisPromptBuilder,
    validate_synthesis_response,
)
from query_refinement_module.schema.model import RefinementAspect


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_aspects():
    """Create sample RefinementAspect objects for testing."""
    return [
        RefinementAspect(
            id="population",
            aspect_name="Population",
            aspect_description="The target population being studied",
            evaluation_criteria="Check population is specific",
        ),
        RefinementAspect(
            id="intervention",
            aspect_name="Intervention",
            aspect_description="The intervention being evaluated",
            evaluation_criteria="Check intervention is defined",
        ),
        RefinementAspect(
            id="outcome",
            aspect_name="Outcome",
            aspect_description="The outcome being measured",
            evaluation_criteria="Check outcome is measurable",
        ),
    ]


@pytest.fixture
def sample_mapping():
    """Sample aspect ID to value mapping."""
    return {
        "population": "adults aged 18-65 with Type 2 diabetes",
        "intervention": "metformin therapy",
        "outcome": "HbA1c reduction",
    }


# =============================================================================
# Tests: SynthesisPromptBuilder
# =============================================================================

class TestSynthesisPromptBuilder:
    """Tests for SynthesisPromptBuilder class."""
    
    def test_get_system_prompt_returns_string(self):
        """Test get_system_prompt returns non-empty string."""
        builder = SynthesisPromptBuilder()
        system_prompt = builder.get_system_prompt()
        
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0
        assert "SYNTHESIS" in system_prompt.upper()
    
    def test_get_synthesis_prompt_includes_original_input(self, sample_aspects, sample_mapping):
        """Test synthesis prompt includes original input."""
        builder = SynthesisPromptBuilder()
        original = "Does metformin help diabetics?"
        
        prompt = builder.get_synthesis_prompt(original, sample_mapping, sample_aspects)
        
        assert original in prompt
        assert "Original Input" in prompt
    
    def test_get_synthesis_prompt_includes_all_dimensions(self, sample_aspects, sample_mapping):
        """Test synthesis prompt includes all clarified dimensions."""
        builder = SynthesisPromptBuilder()
        
        prompt = builder.get_synthesis_prompt("test query", sample_mapping, sample_aspects)
        
        # Check all aspects are included
        assert "Population" in prompt
        assert "Intervention" in prompt
        assert "Outcome" in prompt
        
        # Check all values are included
        assert "adults aged 18-65 with Type 2 diabetes" in prompt
        assert "metformin therapy" in prompt
        assert "HbA1c reduction" in prompt
    
    def test_get_synthesis_prompt_includes_descriptions(self, sample_aspects, sample_mapping):
        """Test synthesis prompt includes aspect descriptions."""
        builder = SynthesisPromptBuilder()
        
        prompt = builder.get_synthesis_prompt("test query", sample_mapping, sample_aspects)
        
        assert "target population being studied" in prompt
        assert "intervention being evaluated" in prompt
    
    def test_get_synthesis_prompt_handles_missing_values(self, sample_aspects):
        """Test synthesis prompt handles aspects with no value in mapping."""
        builder = SynthesisPromptBuilder()
        partial_mapping = {"population": "adults"}  # Missing intervention and outcome
        
        prompt = builder.get_synthesis_prompt("test query", partial_mapping, sample_aspects)
        
        assert "adults" in prompt
        assert "[NOT SET]" in prompt  # Default for missing values
    
    def test_get_synthesis_prompt_handles_skipped(self, sample_aspects):
        """Test synthesis prompt handles [SKIPPED] values."""
        builder = SynthesisPromptBuilder()
        mapping = {
            "population": "adults",
            "intervention": "[SKIPPED]",
            "outcome": "blood pressure",
        }
        
        prompt = builder.get_synthesis_prompt("test query", mapping, sample_aspects)
        
        assert "[SKIPPED]" in prompt
    
    def test_static_method_callable_without_instance(self, sample_aspects, sample_mapping):
        """Test methods work as static methods."""
        system_prompt = SynthesisPromptBuilder.get_system_prompt()
        user_prompt = SynthesisPromptBuilder.get_synthesis_prompt(
            "test query", sample_mapping, sample_aspects
        )
        
        assert isinstance(system_prompt, str)
        assert isinstance(user_prompt, str)


# =============================================================================
# Tests: Response Validation
# =============================================================================

class TestSynthesisResponseValidation:
    """Tests for validate_synthesis_response function."""
    
    def test_valid_response_passes(self):
        """Test valid synthesis response passes validation."""
        response = {
            "synthesized_statement": "A refined research question",
            "refined_dimensions": {"population": "adults"},
            "search_optimized": {
                "semantic": "semantic query",
                "keyword": {
                    "structured": "query",
                    "phrases": [],
                    "terms": {"required": [], "optional": [], "excluded": []},
                },
                "grey_literature": {
                    "broad_concepts": [],
                    "organizational_terms": [],
                    "geographic_variants": [],
                },
            },
            "search_filters": {
                "publication_years": "",
                "venues": "",
                "authors": [],
                "publication_types": [],
                "fields_of_study": "",
            },
            "terminology": {
                "primary_terms": [],
                "synonyms": {},
                "domain_specific": [],
                "colloquial": [],
            },
            "metadata": {
                "temporal": None,
                "geographic": None,
                "source_types": [],
                "other": {},
            },
            "processing_log": {
                "preserved": [],
                "normalized": [],
                "integrated": [],
                "expanded": [],
            },
        }
        
        # Should not raise
        result = validate_synthesis_response(response)
        assert result.synthesized_statement == "A refined research question"
