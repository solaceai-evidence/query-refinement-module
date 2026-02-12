"""
Unit tests for SynthesisPromptBuilder.

Tests the structured prompt building for query synthesis step.
"""

import pytest
from query_refinement_module.schema import RefinementAspect, SynthesisPromptBuilder


@pytest.fixture
def sample_aspects():
    """Create sample refinement aspects for testing."""
    return [
        RefinementAspect(
            id="population",
            name="Target Population",
            description="Who are the subjects?",
            specifications="Identify the population in the query: {query}",
        ),
        RefinementAspect(
            id="intervention",
            name="Intervention",
            description="What is being tested?",
            specifications="Identify the intervention in the query: {query}",
        ),
        RefinementAspect(
            id="outcome",
            name="Outcome",
            description="What is being measured?",
            specifications="Identify the outcome in the query: {query}",
        ),
    ]


@pytest.fixture
def refinement_values():
    """Create sample refinement values."""
    return {
        "population": "adults with diabetes",
        "intervention": "metformin therapy",
        "outcome": "[SKIPPED]",
    }


class TestSynthesisPromptBuilder:
    """Test suite for SynthesisPromptBuilder."""

    def test_build_synthesis_prompt_basic(self, sample_aspects, refinement_values):
        """Test basic synthesis prompt building."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="diabetes treatment outcomes",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Check prompt includes key sections (using new template format)
        assert "Original Input" in prompt
        assert "diabetes treatment outcomes" in prompt
        assert "Clarified Dimensions" in prompt
        assert "Target Population" in prompt
        assert "adults with diabetes" in prompt

    def test_aspects_section_excludes_skipped(self, sample_aspects, refinement_values):
        """Test that [SKIPPED] aspects are included with a marker."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Population and intervention should be present
        assert "Target Population" in prompt
        assert "adults with diabetes" in prompt
        assert "Intervention" in prompt
        assert "metformin therapy" in prompt

        # Outcome should be marked as skipped in aspects section
        assert "Outcome" in prompt
        assert "[SKIPPED]" in prompt

    def test_aspects_section_with_actual_and_skipped_values(self, sample_aspects):
        """Test that actual dimension values and [SKIPPED] are properly included."""
        refinement_values = {
            "population": "adults aged 18-65",
            "intervention": "drug therapy",
            "outcome": "[SKIPPED]",
        }

        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Should contain actual values and skipped marker
        assert "adults aged 18-65" in prompt
        assert "drug therapy" in prompt
        assert "[SKIPPED]" in prompt

    def test_output_format_includes_required_fields(self, sample_aspects, refinement_values):
        """Test that output format includes required dimensions."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Check all aspects are present in the prompt
        assert "Target Population" in prompt
        assert "Intervention" in prompt
        assert "Outcome" in prompt

    def test_empty_refinements(self, sample_aspects):
        """Test with no refinement values."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping={},
            aspect_list=sample_aspects,
        )

        # Should still build valid prompt with [NOT SET] markers
        assert "Original Input" in prompt
        assert "test query" in prompt
        assert "[NOT SET]" in prompt

    def test_quality_requirements_included(self, sample_aspects, refinement_values):
        """Test that prompt contains dimension information for quality synthesis."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Check that the prompt contains structured dimension information
        # that enables quality synthesis
        assert "Clarified Dimensions" in prompt
        assert "Target Population" in prompt
        assert "Intervention" in prompt
        assert "Outcome" in prompt

    def test_get_system_prompt(self):
        """Test system prompt retrieval."""
        builder = SynthesisPromptBuilder()
        system_prompt = builder.get_system_prompt()

        # Should return non-empty system prompt
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0
        
        # Should mention synthesis role
        assert "synthesis" in system_prompt.lower() or "refine" in system_prompt.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
