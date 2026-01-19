"""
Unit tests for SynthesisResponse Pydantic model.

Tests validation and structure of synthesis response output.
"""

import pytest
from pydantic import ValidationError
from query_refinement_module.schema import SynthesisResponse


class TestSynthesisResponse:
    """Test suite for SynthesisResponse model."""

    def test_valid_minimal_response(self):
        """Test creation with minimal required fields."""
        response = SynthesisResponse(
            refined_query="diabetes in adults",
            refinement_aspects={"population": "adults", "condition": "diabetes"},
            confidence=0.9,
        )

        assert response.refined_query == "diabetes in adults"
        assert response.refinement_aspects == {"population": "adults", "condition": "diabetes"}
        assert response.confidence == 0.9
        assert response.key_changes == []  # Default empty list

    def test_valid_response_with_all_fields(self):
        """Test creation with all optional fields."""
        response = SynthesisResponse(
            refined_query="diabetes treatment in adults",
            refinement_aspects={
                "population": "adults",
                "intervention": "metformin",
                "outcome": "glycemic control"
            },
            confidence=0.95,
            key_changes=[
                "Added population specificity",
                "Clarified intervention type",
                "Specified outcome measure"
            ],
            publication_years="2018-2023",
            venues="Diabetes Care, JAMA",
            authors=["Smith J", "Johnson M"],
            fields_of_study="endocrinology, clinical medicine",
            refined_statement="What are the effects of metformin on glycemic control in adults?",
            refined_statement_keywords="metformin glycemic control adults diabetes",
        )

        assert response.refined_query == "diabetes treatment in adults"
        assert len(response.key_changes) == 3
        assert response.publication_years == "2018-2023"
        assert response.venues == "Diabetes Care, JAMA"
        assert len(response.authors) == 2
        assert response.fields_of_study == "endocrinology, clinical medicine"
        assert "metformin" in response.refined_statement
        assert "glycemic" in response.refined_statement_keywords

    def test_missing_required_field_refined_query(self):
        """Test validation fails without refined_query."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refinement_aspects={"population": "adults"},
                confidence=0.9,
            )
        
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("refined_query",) for e in errors)

    def test_missing_required_field_refinement_aspects(self):
        """Test validation fails without refinement_aspects."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refined_query="test query",
                confidence=0.9,
            )
        
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("refinement_aspects",) for e in errors)

    def test_missing_required_field_confidence(self):
        """Test validation fails without confidence."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refined_query="test query",
                refinement_aspects={"population": "adults"},
            )
        
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("confidence",) for e in errors)

    def test_confidence_validation_too_low(self):
        """Test confidence must be >= 0.0."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refined_query="test query",
                refinement_aspects={"population": "adults"},
                confidence=-0.1,
            )
        
        errors = exc_info.value.errors()
        assert any("confidence" in str(e["loc"]) for e in errors)

    def test_confidence_validation_too_high(self):
        """Test confidence must be <= 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refined_query="test query",
                refinement_aspects={"population": "adults"},
                confidence=1.1,
            )
        
        errors = exc_info.value.errors()
        assert any("confidence" in str(e["loc"]) for e in errors)

    def test_confidence_boundary_values(self):
        """Test confidence boundary values 0.0 and 1.0."""
        # Test 0.0
        response_min = SynthesisResponse(
            refined_query="test",
            refinement_aspects={},
            confidence=0.0,
        )
        assert response_min.confidence == 0.0

        # Test 1.0
        response_max = SynthesisResponse(
            refined_query="test",
            refinement_aspects={},
            confidence=1.0,
        )
        assert response_max.confidence == 1.0

    def test_refinement_aspects_must_be_dict(self):
        """Test refinement_aspects must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            SynthesisResponse(
                refined_query="test query",
                refinement_aspects="not a dict",
                confidence=0.9,
            )
        
        errors = exc_info.value.errors()
        assert any("refinement_aspects" in str(e["loc"]) for e in errors)

    def test_default_empty_values(self):
        """Test default values for optional fields."""
        response = SynthesisResponse(
            refined_query="test query",
            refinement_aspects={"test": "value"},
            confidence=0.8,
        )

        assert response.key_changes == []
        assert response.publication_years == ""
        assert response.venues == ""
        assert response.authors == []
        assert response.fields_of_study == ""
        assert response.refined_statement == ""
        assert response.refined_statement_keywords == ""

    def test_refinement_aspects_with_special_values(self):
        """Test refinement_aspects can contain special markers."""
        response = SynthesisResponse(
            refined_query="test query",
            refinement_aspects={
                "population": "adults",
                "outcome": "[SKIPPED]",
                "intervention": "[CLEAR_IN_ORIGINAL]",
            },
            confidence=0.85,
        )

        assert response.refinement_aspects["outcome"] == "[SKIPPED]"
        assert response.refinement_aspects["intervention"] == "[CLEAR_IN_ORIGINAL]"

    def test_model_allows_updates(self):
        """Test model configuration allows field updates."""
        response = SynthesisResponse(
            refined_query="original",
            refinement_aspects={"test": "value"},
            confidence=0.5,
        )

        # Should allow updates (frozen=False in Config)
        response.confidence = 0.9
        assert response.confidence == 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
