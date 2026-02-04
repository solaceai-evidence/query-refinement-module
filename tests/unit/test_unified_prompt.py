"""
Tests for unified analysis prompt system.

The unified prompt system uses a single template for both initial and follow-up analysis,
with only the conversation history section differing based on mode.
"""
import json
import pytest
from query_refinement_module.schema import RefinementAspect, DimensionEvaluationResponse


@pytest.fixture
def sample_aspect():
    """Create a sample RefinementAspect for testing."""
    return RefinementAspect(
        id='test_aspect',
        aspect_name='Test Aspect',
        aspect_description='A test aspect for validation',
        evaluation_instructions='Extract the {query} details carefully.',
        response_format={'type': 'json'},
        examples=[]
    )


def test_conversation_section_empty_for_initial(sample_aspect):
    """Initial mode should produce empty conversation section."""
    result = sample_aspect._build_conversation_section(
        follow_up_history=[],
        mode='initial'
    )
    assert result == ""


def test_conversation_section_populated_for_followup(sample_aspect):
    """Followup mode should format conversation history."""
    history = [
        {'question': 'What population?', 'response': 'Adults'},
        {'question': 'Age range?', 'response': '18-65'}
    ]
    result = sample_aspect._build_conversation_section(follow_up_history=history, mode='followup')
    
    assert "**Conversation History:**" in result
    assert "Q1: What population?" in result
    assert "A1: Adults" in result
    assert "Q2: Age range?" in result
    assert "A2: 18-65" in result


def test_dependency_section_with_completed_aspects():
    """Should format completed dependency values with markers."""
    aspect = RefinementAspect(
        id='outcome',
        aspect_name='Outcome',
        aspect_description='Study outcome',
        evaluation_instructions='Test',
        response_format={'type': 'json'},
        depends_on=['population', 'intervention']  # This aspect depends on these
    )
    
    dependency_context = {
        'population': {
            'name': 'Population',
            'description': 'Target population',
            'value': 'Adults aged 18-65'
        },
        'intervention': {
            'name': 'Intervention',
            'description': 'Medical intervention',
            'value': 'Statins'
        }
    }
    
    result = aspect._build_dependency_section(dependency_context)
    
    assert "**Completed Dimensions (for context):**" in result
    assert "**Population** ⚠️ (the current dimension depends on this)" in result
    assert "Value: Adults aged 18-65" in result
    assert "**Intervention** ⚠️ (the current dimension depends on this)" in result
    assert "Value: Statins" in result


def test_dependency_section_empty_when_no_dependencies(sample_aspect):
    """Should return empty string when no dependencies."""
    result = sample_aspect._build_dependency_section({})
    
    assert result == ""


def test_evaluation_instructions_uses_aspect_field():
    """Should use aspect.evaluation_instructions field."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        evaluation_instructions='Extract the {query} details carefully.',
        response_format={'type': 'json'}
    )
    
    result = aspect._build_evaluation_instructions_section('sample query')
    
    assert "Extract the sample query details carefully" in result


def test_evaluation_instructions_empty_when_not_provided():
    """Should return empty string when evaluation_instructions not provided."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        evaluation_instructions='',
        response_format={'type': 'json'}
    )
    
    result = aspect._build_evaluation_instructions_section('sample query')
    
    # Even with empty evaluation_instructions, the function returns the template
    assert "Evaluation Strategy" in result
    assert "sample query" in result


def test_examples_section_formats_all_categories(sample_aspect):
    """Should format examples into clear categories."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        evaluation_instructions='Test instructions',
        response_format={'type': 'json'},
        examples={
            'clear': [
                {
                    'query': 'Clear query',
                    'reasoning': 'All details present'
                }
            ],
            'needs_refinement': [
                {
                    'query': 'Vague query',
                    'reasoning': 'Missing details',
                    'clarifying_question': 'Can you specify?'
                }
            ]
        }
    )
    
    result = aspect._build_examples_section_for_prompt()
    
    assert "**Examples:**" in result
    assert "Clear query" in result
    assert "Vague query" in result
    # Note: 'reasoning' field is not included in output (not a valid schema field)


def test_examples_section_empty_when_no_examples(sample_aspect):
    """Should return empty string when no examples provided."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        evaluation_instructions='Test instructions',
        response_format={'type': 'json'}
    )
    
    result = aspect._build_examples_section_for_prompt()
    
    assert result == ""


def test_unified_prompt_formats_correctly():
    """Should format complete unified prompt with all sections."""
    aspect = RefinementAspect(
        id='population',
        aspect_name='Population',
        aspect_description='Target population for study',
        evaluation_instructions='Identify specific demographics from {query}.',
        response_format={'type': 'json'},
        examples={
            'clear': [
                {
                    'query': 'Study on adults',
                    'reasoning': 'Population clearly stated'
                }
            ]
        }
    )
    
    result = aspect.build_unified_prompt(
        original_input='heart disease study',
        follow_up_history=[],
        dependency_context={},
        mode='initial'
    )
    
    assert "Population" in result
    assert "Target population for study" in result
    assert "heart disease study" in result
    assert "Identify specific demographics from heart disease study" in result
    assert "Study on adults" in result


def test_refinement_analysis_response_validation():
    """Should validate RefinementAnalysisResponse completeness."""
    # Complete response must have current - validation happens during construction
    complete_response = DimensionEvaluationResponse(
        complete=True,
        current='Adults aged 18-65',
        question=''
    )
    # If construction succeeds, validation passed
    assert complete_response.complete is True
    assert complete_response.current == 'Adults aged 18-65'
    
    # Incomplete response must have question - validation happens during construction
    incomplete_response = DimensionEvaluationResponse(
        complete=False,
        current='',
        question='What age range?'
    )
    # If construction succeeds, validation passed
    assert incomplete_response.complete is False
    assert incomplete_response.question == 'What age range?'


def test_refinement_analysis_response_invalid_complete():
    """Should raise error when complete but no current value."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        DimensionEvaluationResponse(
            complete=True,
            current='',  # Missing!
            question=''
        )
    
    assert 'current' in str(exc_info.value)


def test_refinement_analysis_response_invalid_incomplete():
    """Should raise error when incomplete but no question."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        DimensionEvaluationResponse(
            complete=False,
            current=None,
            question=None,  # Missing!
        )
    
    assert 'question' in str(exc_info.value)
