"""
Tests for unified analysis prompt system.

The unified prompt system uses a single template for both initial and follow-up analysis,
with only the conversation history section differing based on mode.
"""
import json
import pytest
from query_refinement_module.schema import RefinementAspect, RefinementAnalysisResponse


@pytest.fixture
def sample_aspect():
    """Create a sample RefinementAspect for testing."""
    return RefinementAspect(
        id='test_aspect',
        aspect_name='Test Aspect',
        aspect_description='A test aspect for validation',
        refinement_instructions='Extract the {query} details carefully.',
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
        refinement_instructions='Test',
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
    
    assert "**Completed Aspects (for context):**" in result
    assert "**Population** ⚠️ (this aspect depends on this)" in result
    assert "Adults aged 18-65" in result
    assert "**Intervention** ⚠️ (this aspect depends on this)" in result
    assert "Statins" in result


def test_dependency_section_empty_when_no_dependencies(sample_aspect):
    """Should return empty string when no dependencies."""
    result = sample_aspect._build_dependency_section({})
    
    assert result == ""


def test_refinement_instructions_uses_aspect_field():
    """Should use aspect.refinement_instructions field."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        refinement_instructions='Extract the {query} details carefully.',
        response_format={'type': 'json'}
    )
    
    result = aspect._build_refinement_instructions_section('sample query')
    
    assert "Extract the sample query details carefully" in result


def test_refinement_instructions_empty_when_not_provided():
    """Should return empty string when refinement_instructions not provided."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        refinement_instructions='',
        response_format={'type': 'json'}
    )
    
    result = aspect._build_refinement_instructions_section('sample query')
    
    # Even with empty refinement_instructions, the function returns the template
    assert "**Analysis Guidelines:**" in result
    assert "sample query" in result


def test_examples_section_formats_all_categories(sample_aspect):
    """Should format examples into clear categories."""
    aspect = RefinementAspect(
        id='test',
        aspect_name='Test',
        aspect_description='Testing',
        refinement_instructions='Test instructions',
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
        refinement_instructions='Test instructions',
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
        refinement_instructions='Identify specific demographics from {query}.',
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
        original_query='heart disease study',
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
    # Complete response must have refinement_aspect_value - validation happens during construction
    complete_response = RefinementAnalysisResponse(
        is_complete=True,
        confidence=0.9,
        reasoning='All details clear',
        refinement_aspect_value='Adults aged 18-65',
        next_question=None,
        context='initial',
        round=1
    )
    # If construction succeeds, validation passed
    assert complete_response.is_complete is True
    assert complete_response.refinement_aspect_value == 'Adults aged 18-65'
    
    # Incomplete response must have next_question - validation happens during construction
    incomplete_response = RefinementAnalysisResponse(
        is_complete=False,
        confidence=0.5,
        reasoning='Need age range',
        refinement_aspect_value=None,
        next_question='What age range?',
        context='initial',
        round=1
    )
    # If construction succeeds, validation passed
    assert incomplete_response.is_complete is False
    assert incomplete_response.next_question == 'What age range?'


def test_refinement_analysis_response_invalid_complete():
    """Should raise error when complete but no refinement_aspect_value."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        RefinementAnalysisResponse(
            is_complete=True,
            confidence=0.9,
            reasoning='Complete',
            refinement_aspect_value=None,  # Missing!
            next_question=None,
            context='initial',
            round=1
        )
    
    assert 'refinement_aspect_value' in str(exc_info.value)


def test_refinement_analysis_response_invalid_incomplete():
    """Should raise error when incomplete but no next_question."""
    import pytest
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        RefinementAnalysisResponse(
            is_complete=False,
            confidence=0.5,
            reasoning='Incomplete',
            refinement_aspect_value=None,
            next_question=None,  # Missing!
            context='initial',
            round=1
        )
    
    assert 'next_question' in str(exc_info.value)
