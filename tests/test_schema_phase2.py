"""
Phase 2 tests for schema module with Pydantic models and Jinja2 templates.
"""

import pytest
from query_refinement_module.schema import (
    # Models
    RefinementDimension,
    RefinementAspect,
    CompletedDimension,
    ExamplesCollection,
    ClearExample,
    # Registry
    list_frameworks,
    get_framework,
    # Prompt builder
    PromptBuilder,
    SynthesisPromptBuilder,
    get_prompt_builder,
    render_template,
    # Templates
    GLOBAL_SYSTEM_PROMPT,
    SYNTHESIS_TEMPLATE,
    DIMENSION_REFINEMENT_TEMPLATE,
)


class TestPydanticModels:
    """Test the Pydantic model classes."""

    def test_refinement_dimension_basic(self):
        """Test creating a basic RefinementDimension."""
        dim = RefinementDimension(
            id="test_dim",
            name="Test Dimension",
            description="A test dimension",
            specifications="Test criteria"
        )
        assert dim.id == "test_dim"
        assert dim.name == "Test Dimension"
        assert dim.specifications == "Test criteria"

    def test_refinement_aspect_is_alias(self):
        """Test that RefinementAspect is an alias for RefinementDimension."""
        assert RefinementAspect is RefinementDimension

    def test_completed_dimension_model(self):
        """Test CompletedDimension model."""
        completed = CompletedDimension(
            id="test",
            name="Test",
            description="Test description",
            assembled_value="Test value"
        )
        assert completed.assembled_value == "Test value"

    def test_examples_collection_model(self):
        """Test ExamplesCollection model."""
        examples = ExamplesCollection(
            clear=[ClearExample(statement="Test statement", rationale="Test rationale")]
        )
        assert len(examples.clear) == 1
        assert examples.has_examples() == True


class TestFrameworkLoading:
    """Test framework loading with new models."""

    def test_list_frameworks(self):
        """Test that frameworks can be listed."""
        frameworks = list_frameworks()
        assert isinstance(frameworks, list)
        assert len(frameworks) > 0

    def test_get_framework(self):
        """Test getting a framework by name."""
        frameworks = list_frameworks()
        if frameworks:
            fw = get_framework(frameworks[0])
            assert isinstance(fw, list)
            assert len(fw) > 0

    def test_framework_aspects_are_pydantic(self):
        """Test that loaded aspects are Pydantic models."""
        frameworks = list_frameworks()
        if frameworks:
            fw = get_framework(frameworks[0])
            for aspect in fw:
                assert isinstance(aspect, RefinementDimension)

    def test_framework_first_item_is_dimension(self):
        """Test that the first item in a loaded framework is a dimension, not a user_context block."""
        frameworks = list_frameworks()
        if frameworks:
            fw = get_framework(frameworks[0])
            assert fw, "Framework should have dimensions"
            first = fw[0]
            assert first.id, "First item should be a dimension with an id"
            assert first.name, "First item should be a dimension with a name"


class TestPromptBuilder:
    """Test the PromptBuilder class."""

    def test_get_prompt_builder(self):
        """Test getting default prompt builder."""
        builder = get_prompt_builder()
        assert isinstance(builder, PromptBuilder)

    def test_global_system_prompt(self):
        """Test getting global system prompt."""
        builder = PromptBuilder()
        prompt = builder.get_global_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 1000
        assert "Research Query Refinement" in prompt

    def test_global_system_prompt_has_interaction_style(self):
        """Global prompt should contain the question-asking behaviour rules."""
        builder = PromptBuilder()
        prompt = builder.get_global_system_prompt()
        assert "INTERACTION STYLE" in prompt
        assert "1 focused question" in prompt
        assert "ONLY these 4 fields" in prompt

    def test_global_system_prompt_scopes_opt_out_rules(self):
        """Opt-out completion rules should not complete core content dimensions by default."""
        builder = PromptBuilder()
        prompt = builder.get_global_system_prompt()
        assert "no-restriction answer" in prompt
        assert "For core content dimensions" in prompt
        assert "continue assessing" in prompt
        assert "required elements" in prompt

    def test_render_dimension_prompt(self):
        """Test rendering dimension prompt."""
        builder = PromptBuilder()
        dim = RefinementDimension(
            id="test",
            name="Test Dimension",
            description="Test description",
            specifications="Test criteria"
        )
        rendered = builder.render_dimension_prompt(dim)
        assert "Test Dimension" in rendered
        assert "Test description" in rendered
        assert "Test criteria" in rendered

    def test_render_completed_dimensions(self):
        """Test rendering completed dimensions section."""
        builder = PromptBuilder()
        completed = [
            CompletedDimension(
                id="test1",
                name="Test 1",
                description="First test",
                assembled_value="Value 1"
            )
        ]
        rendered = builder.render_completed_dimensions(completed)
        assert "Test 1" in rendered
        assert "Value 1" in rendered

    def test_build_refinement_system_prompt(self):
        """Test building complete refinement system prompt."""
        builder = PromptBuilder()
        dim = RefinementDimension(
            id="test",
            name="Test Dimension",
            description="Test description",
            specifications="Test criteria",
        )

        prompt = builder.build_refinement_system_prompt(dimension=dim)

        assert "Research Query Refinement" in prompt
        assert "Test Dimension" in prompt

    def test_get_synthesis_system_prompt(self):
        """Test getting synthesis system prompt."""
        builder = SynthesisPromptBuilder()
        prompt = builder.get_system_prompt()
        assert isinstance(prompt, str)
        assert "SYNTHESIS" in prompt or "integrated_statement" in prompt


class TestTemplates:
    """Test template constants."""

    def test_global_system_prompt_exists(self):
        """Test global system prompt template exists."""
        assert GLOBAL_SYSTEM_PROMPT is not None
        assert len(GLOBAL_SYSTEM_PROMPT) > 0

    def test_synthesis_template_exists(self):
        """Test synthesis template exists."""
        assert SYNTHESIS_TEMPLATE is not None
        assert len(SYNTHESIS_TEMPLATE) > 0

    def test_dimension_template_exists(self):
        """Test dimension template exists."""
        assert DIMENSION_REFINEMENT_TEMPLATE is not None
        assert len(DIMENSION_REFINEMENT_TEMPLATE) > 0


class TestIntegration:
    """Integration tests with real framework data."""

    def test_full_prompt_with_real_framework(self):
        """Test building full prompt with real framework data."""
        frameworks = list_frameworks()
        if not frameworks:
            pytest.skip("No frameworks available")

        fw = get_framework(frameworks[0])
        if not fw:
            pytest.skip("Framework has no aspects")

        builder = PromptBuilder()
        dim = fw[0]

        prompt = builder.build_refinement_system_prompt(dimension=dim)

        assert "Research Query Refinement" in prompt
        assert dim.name in prompt
        assert len(prompt) > 5000

    def test_dimension_with_examples(self):
        """Test dimension with examples renders correctly."""
        frameworks = list_frameworks()
        if not frameworks:
            pytest.skip("No frameworks available")

        fw = get_framework(frameworks[0])

        dim_with_examples = next(
            (d for d in fw if d.examples and d.has_examples()),
            None,
        )
        if not dim_with_examples:
            pytest.skip("No dimension with examples found")

        builder = PromptBuilder()
        rendered = builder.render_dimension_prompt(dim_with_examples)

        assert "Clear Specifications" in rendered or "Examples" in rendered
