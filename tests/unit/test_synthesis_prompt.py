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
            aspect_name="Target Population",
            aspect_description="Who are the subjects?",
            evaluation_instructions="Identify the population in the query: {query}",
        ),
        RefinementAspect(
            id="intervention",
            aspect_name="Intervention",
            aspect_description="What is being tested?",
            evaluation_instructions="Identify the intervention in the query: {query}",
        ),
        RefinementAspect(
            id="outcome",
            aspect_name="Outcome",
            aspect_description="What is being measured?",
            evaluation_instructions="Identify the outcome in the query: {query}",
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

        # Check prompt includes key sections
        assert "ORIGINAL INPUT" in prompt
        assert "diabetes treatment outcomes" in prompt
        assert "CLARIFIED DETAILS" in prompt
        assert "Target Population" in prompt
        assert "adults with diabetes" in prompt
        assert "OUTPUT STRUCTURE" in prompt
        assert "OUTPUT FORMAT" in prompt
        assert "synthesized_statement" in prompt
        assert "detail_values" in prompt

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
        aspects_section = prompt.split("OUTPUT FORMAT")[0]
        assert "Outcome" in aspects_section
        assert "[SKIPPED]" in aspects_section

    def test_aspects_section_handles_clear_in_original(self, sample_aspects):
        """Test that [CLEAR_IN_ORIGINAL] aspects are included with a marker."""
        refinement_values = {
            "population": "[CLEAR_IN_ORIGINAL]",
            "intervention": "drug therapy",
            "outcome": "[SKIPPED]",
        }

        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Should contain clear in original marker
        assert "[CLEAR_IN_ORIGINAL]" in prompt

    def test_output_format_includes_required_fields(self, sample_aspects, refinement_values):
        """Test that output format includes all required fields."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Check all required fields are present
        assert '"synthesized_statement"' in prompt
        assert '"detail_values"' in prompt
        assert '"search_optimized"' in prompt
        assert '"search_filters"' in prompt
        assert '"terminology"' in prompt
        assert '"metadata"' in prompt
        assert '"processing_log"' in prompt

    def test_empty_refinements(self, sample_aspects):
        """Test with no refinement values."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping={},
            aspect_list=sample_aspects,
        )

        # Should still build valid prompt
        assert "ORIGINAL INPUT" in prompt
        assert "test query" in prompt
        assert "OUTPUT FORMAT" in prompt

    def test_quality_requirements_included(self, sample_aspects, refinement_values):
        """Test that quality requirements are included in prompt."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_synthesis_prompt(
            original_input="test query",
            aspectID_value_mapping=refinement_values,
            aspect_list=sample_aspects,
        )

        # Check for quality guidance
        quality_markers = [
            "preserve",
            "combine",
            "natural",
            "specific",
            "clear",
        ]
        
        # At least some quality guidance should be present
        found_markers = sum(1 for marker in quality_markers if marker.lower() in prompt.lower())
        assert found_markers >= 2, "Quality requirements should be present in prompt"

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
