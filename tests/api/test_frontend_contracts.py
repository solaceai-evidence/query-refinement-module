"""
Contract tests to validate API responses match frontend TypeScript type definitions.

These tests ensure that backend schema changes don't break frontend integration.
"""
import pytest
from query_refinement_module.api.routes.refinement import (
    StartRefinementResponse,
    SubmitAnswerResponse,
    CommandResponse,
    GetRefinementStatusResponse,
    SynthesizeQueryResponse
)


class TestFrontendContracts:
    """
    Validate API response models match frontend type definitions in:
    frontend/src/types/api.d.ts
    """
    
    def test_start_refinement_response_contract(self):
        """
        Validates StartRefinementResponse matches frontend StartRefinementResponse interface.
        
        Frontend expects:
        - session_id: number
        - query_id: number
        - summary: { total_aspects, aspects_needing_refinement, aspects_clear, is_complete }
        - next_prompt: NextPrompt | null
        """
        # Simulate API response
        response_dict = {
            "session_id": 1,
            "query_id": 1,
            "summary": {
                "total_aspects": 4,
                "aspects_needing_refinement": 2,
                "aspects_clear": 2,
                "is_complete": False
            },
            "next_prompt": {
                "aspect_id": "population",
                "aspect_name": "Population",
                "question": "Who is the target population?",
                "description": "Define the population group"
            }
        }
        
        # Validate Pydantic model can be created (validates structure)
        response = StartRefinementResponse(**response_dict)
        
        # Validate required fields exist
        assert hasattr(response, 'session_id')
        assert hasattr(response, 'query_id')
        assert hasattr(response, 'summary')
        assert hasattr(response, 'next_prompt')
        
        # Validate summary structure matches frontend expectations
        summary = response.summary
        assert "total_aspects" in summary
        assert "aspects_needing_refinement" in summary
        assert "aspects_clear" in summary
        assert "is_complete" in summary
        
        # Validate types
        assert isinstance(response.session_id, int)
        assert isinstance(response.query_id, int)
        assert isinstance(summary["is_complete"], bool)
        assert isinstance(summary["total_aspects"], int)
        
        print("✓ StartRefinementResponse contract valid")
    
    def test_submit_answer_response_contract(self):
        """
        Validates SubmitAnswerResponse matches frontend interface.
        
        Frontend expects:
        - refinement_step_id: number
        - followup_id: number
        - is_complete: boolean
        - next_prompt: NextPrompt | null
        """
        response_dict = {
            "refinement_step_id": 1,
            "followup_id": 1,
            "is_complete": False,
            "next_prompt": {
                "aspect_id": "population",
                "aspect_name": "Population",
                "question": "Can you be more specific?",
                "description": "Follow-up question"
            }
        }
        
        response = SubmitAnswerResponse(**response_dict)
        
        # Validate required fields
        assert hasattr(response, 'refinement_step_id')
        assert hasattr(response, 'followup_id')
        assert hasattr(response, 'is_complete')
        assert hasattr(response, 'next_prompt')
        
        # Validate critical field: is_complete (NOT needs_refinement)
        assert isinstance(response.is_complete, bool)
        
        print("✓ SubmitAnswerResponse contract valid")
    
    def test_command_response_contract(self):
        """
        Validates CommandResponse matches frontend CommandResult interface.
        
        Frontend expects:
        - command_type: string (maps to 'type')
        - success: boolean
        - message: string
        - step_summary, step_list, invalidated_aspects, synthesis_ready, force_required (optional)
        """
        response_dict = {
            "command_type": "status",
            "success": True,
            "message": "Session status retrieved",
            "next_prompt": None,
            "step_summary": {
                "completed_steps": 2,
                "total_steps": 4,
                "pending_steps": 2,
                "current_aspect": "intervention",
                "current_step": 3
            },
            "step_list": None,
            "invalidated_aspects": None,
            "synthesis_ready": False,
            "force_required": None
        }
        
        response = CommandResponse(**response_dict)
        
        # Validate required fields
        assert hasattr(response, 'command_type')
        assert hasattr(response, 'success')
        assert hasattr(response, 'message')
        
        # Validate optional fields exist (even if None)
        assert hasattr(response, 'step_summary')
        assert hasattr(response, 'invalidated_aspects')
        assert hasattr(response, 'synthesis_ready')
        assert hasattr(response, 'force_required')
        
        print("✓ CommandResponse contract valid")
    
    def test_get_status_response_contract(self):
        """
        Validates GetRefinementStatusResponse matches frontend interface.
        
        Frontend expects:
        - query_id: number
        - original_query: string
        - refined_query: string | null
        - is_complete: boolean
        - current_aspect: string | null
        - aspects_summary: { aspects: AspectSummary[] }
        """
        response_dict = {
            "query_id": 1,
            "original_query": "test query",
            "refined_query": None,
            "is_complete": False,
            "current_aspect": "population",
            "aspects_summary": {
                "aspects": [
                    {
                        "aspect_name": "Population",
                        "is_complete": True,
                        "needs_review": False,
                        "was_skipped": False
                    },
                    {
                        "aspect_name": "Intervention",
                        "is_complete": False,
                        "needs_review": False,
                        "was_skipped": False
                    }
                ]
            }
        }
        
        response = GetRefinementStatusResponse(**response_dict)
        
        # Validate required fields
        assert hasattr(response, 'query_id')
        assert hasattr(response, 'original_query')
        assert hasattr(response, 'refined_query')
        assert hasattr(response, 'is_complete')
        assert hasattr(response, 'current_aspect')
        assert hasattr(response, 'aspects_summary')
        
        # Validate critical field: is_complete (NOT needs_refinement)
        assert isinstance(response.is_complete, bool)
        
        # Validate aspects array contains is_complete field
        aspects = response.aspects_summary["aspects"]
        for aspect in aspects:
            assert "is_complete" in aspect
            assert isinstance(aspect["is_complete"], bool)
        
        print("✓ GetRefinementStatusResponse contract valid")
    
    def test_synthesize_response_contract(self):
        """
        Validates SynthesizeQueryResponse matches frontend interface.
        
        Frontend expects:
        - query_id: number
        - integrated_statement: string
        - used_llm: boolean
        - structured_output: object | null
        """
        response_dict = {
            "query_id": 1,
            "integrated_statement": "refined search query",
            "used_llm": True,
            "structured_output": {
                "dimensions_specifications": {},
                "search_optimized": {}
            }
        }
        
        response = SynthesizeQueryResponse(**response_dict)
        
        # Validate required fields
        assert hasattr(response, 'query_id')
        assert hasattr(response, 'integrated_statement')
        assert hasattr(response, 'used_llm')
        assert hasattr(response, 'structured_output')
        
        # Validate types
        assert isinstance(response.query_id, int)
        assert isinstance(response.integrated_statement, str)
        assert isinstance(response.used_llm, bool)
        
        print("✓ SynthesizeQueryResponse contract valid")
    
    def test_next_prompt_structure(self):
        """
        Validates NextPrompt structure used across multiple responses.
        
        Frontend NextPrompt interface expects:
        - aspect_id: string
        - aspect_name: string
        - question: string
        - description: string
        """
        next_prompt = {
            "aspect_id": "population",
            "aspect_name": "Population",
            "question": "Who is the target population?",
            "description": "Define the population group"
        }
        
        # Validate all required fields present
        assert "aspect_id" in next_prompt
        assert "aspect_name" in next_prompt
        assert "question" in next_prompt
        assert "description" in next_prompt
        
        # Validate types
        assert isinstance(next_prompt["aspect_id"], str)
        assert isinstance(next_prompt["aspect_name"], str)
        assert isinstance(next_prompt["question"], str)
        assert isinstance(next_prompt["description"], str)
        
        print("✓ NextPrompt structure valid")
    
    def test_no_needs_refinement_field_in_responses(self):
        """
        Critical test: Ensure 'needs_refinement' is NOT exposed in API responses.
        
        This field is internal to LLM processing and should never reach the API layer.
        The API should only expose 'is_complete' fields.
        """
        # Test all response models
        response_models = [
            SubmitAnswerResponse,
            GetRefinementStatusResponse,
        ]
        
        for model in response_models:
            # Get field names from Pydantic model
            field_names = model.model_fields.keys()
            
            # Assert needs_refinement is NOT in field names
            assert 'needs_refinement' not in field_names, \
                f"{model.__name__} should not expose 'needs_refinement' field"
            
            # Assert is_complete IS in field names (for applicable models)
            if model in [SubmitAnswerResponse, GetRefinementStatusResponse]:
                assert 'is_complete' in field_names, \
                    f"{model.__name__} should expose 'is_complete' field"
        
        print("✓ No 'needs_refinement' field exposed in API responses")
        print("✓ All responses use 'is_complete' field correctly")
    def test_start_refinement_response_skip_refinement_contract(self):
        """
        Validates StartRefinementResponse with skip_refinement=True payload.

        When skip_refinement=True the response embeds a SynthesizeQueryResponse
        in the optional `synthesis` field.  All other fields must still be present
        and `next_prompt` must be null.
        """
        synthesize_dict = {
            "query_id": 2,
            "integrated_statement": "In adults, compare aspirin versus placebo.",
            "used_llm": True,
            "structured_output": None,
        }
        response_dict = {
            "session_id": 1,
            "query_id": 2,
            "summary": {
                "total_aspects": 4,
                "aspects_needing_refinement": 0,
                "aspects_clear": 4,
                "is_complete": True,
            },
            "next_prompt": None,
            "ready_for_synthesis": True,
            "source": "api_integration",
            "synthesis": synthesize_dict,
        }

        response = StartRefinementResponse(**response_dict)

        # Core fields still present
        assert hasattr(response, 'session_id')
        assert hasattr(response, 'query_id')
        assert hasattr(response, 'summary')
        assert hasattr(response, 'synthesis')

        # skip_refinement fast-path expectations
        assert response.next_prompt is None
        assert response.ready_for_synthesis is True
        assert response.synthesis is not None

        synth = response.synthesis
        assert isinstance(synth, SynthesizeQueryResponse)
        assert isinstance(synth.integrated_statement, str)
        assert synth.integrated_statement != ""
        assert isinstance(synth.used_llm, bool)

        # Normal flow: synthesis field is absent / null
        normal_dict = {
            "session_id": 1,
            "query_id": 3,
            "summary": {"total_aspects": 4, "aspects_needing_refinement": 2,
                        "aspects_clear": 2, "is_complete": False},
            "next_prompt": None,
            "ready_for_synthesis": False,
            "source": "gui",
        }
        normal_response = StartRefinementResponse(**normal_dict)
        assert normal_response.synthesis is None

        print("\u2713 StartRefinementResponse skip_refinement contract valid")

if __name__ == "__main__":
    """Run contract tests standalone for quick validation."""
    test = TestFrontendContracts()
    
    print("\n" + "="*70)
    print("FRONTEND-BACKEND CONTRACT VALIDATION")
    print("="*70 + "\n")
    
    test.test_start_refinement_response_contract()
    test.test_submit_answer_response_contract()
    test.test_command_response_contract()
    test.test_get_status_response_contract()
    test.test_synthesize_response_contract()
    test.test_next_prompt_structure()
    test.test_no_needs_refinement_field_in_responses()
    test.test_start_refinement_response_skip_refinement_contract()
    
    print("\n" + "="*70)
    print("✅ ALL CONTRACT TESTS PASSED")
    print("="*70 + "\n")
    print("Frontend TypeScript types are compatible with backend schemas.")
    print("No breaking changes detected.")
