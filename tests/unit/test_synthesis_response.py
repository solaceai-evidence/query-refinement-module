"""
Unit tests for QueryRefinementResponse Pydantic model.

Tests validation and structure of synthesis response output.
"""

import pytest
from pydantic import ValidationError
from query_refinement_module.schema import QueryRefinementResponse


class TestSynthesisResponse:
    """Test suite for QueryRefinementResponse model."""

    def _base_payload(self):
        return {
            "synthesized_statement": "diabetes in adults",
            "detail_values": {"population": "adults", "condition": "diabetes"},
            "search_optimized": {
                "semantic": "Semantic search query for diabetes in adults",
                "keyword": {
                    "structured": "(diabetes) AND (adults)",
                    "phrases": ["diabetes adults"],
                    "terms": {
                        "required": ["diabetes"],
                        "optional": ["adult"],
                        "excluded": [],
                    },
                },
                "grey_literature": {
                    "broad_concepts": ["adult diabetes"],
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
                "primary_terms": ["diabetes"],
                "synonyms": {"diabetes": ["T2DM"]},
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
                "preserved": ["diabetes"],
                "normalized": [],
                "integrated": [],
                "expanded": [],
            },
        }

    def test_valid_minimal_response(self):
        """Test creation with minimal required fields."""
        response = QueryRefinementResponse(**self._base_payload())

        assert response.synthesized_statement == "diabetes in adults"
        assert response.refined_dimensions == {"population": "adults", "condition": "diabetes"}
        assert response.search_filters.publication_years == ""

    def test_valid_response_with_all_fields(self):
        """Test creation with all optional fields."""
        payload = self._base_payload()
        payload["synthesized_statement"] = "diabetes treatment in adults"
        payload["detail_values"].update(
            {
                "intervention": "metformin",
                "outcome": "glycemic control",
            }
        )
        payload["search_filters"].update(
            {
                "publication_years": "2018-2023",
                "venues": "Diabetes Care, JAMA",
                "authors": ["Smith J", "Johnson M"],
                "fields_of_study": "endocrinology, clinical medicine",
            }
        )

        response = QueryRefinementResponse(**payload)

        assert response.synthesized_statement == "diabetes treatment in adults"
        assert response.search_filters.publication_years == "2018-2023"
        assert response.search_filters.venues == "Diabetes Care, JAMA"
        assert len(response.search_filters.authors) == 2
        assert response.search_filters.fields_of_study == "endocrinology, clinical medicine"

    def test_missing_required_field_synthesized_statement(self):
        """Test validation fails without synthesized_statement."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload.pop("synthesized_statement")
            QueryRefinementResponse(**payload)
        
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("synthesized_statement",) for e in errors)

    def test_missing_required_field_detail_values(self):
        """Test validation fails without detail_values."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload.pop("detail_values")
            QueryRefinementResponse(**payload)
        
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("detail_values",) for e in errors)

    def test_detail_values_must_be_dict(self):
        """Test detail_values must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload["detail_values"] = "not a dict"
            QueryRefinementResponse(**payload)
        
        errors = exc_info.value.errors()
        assert any("detail_values" in str(e["loc"]) for e in errors)

    def test_default_empty_values(self):
        """Test default values for optional fields."""
        response = QueryRefinementResponse(**self._base_payload())

        assert response.search_filters.publication_years == ""
        assert response.search_filters.venues == ""
        assert response.search_filters.authors == []
        assert response.search_filters.fields_of_study == ""

    def test_detail_values_with_special_values(self):
        """Test detail_values can contain special markers."""
        payload = self._base_payload()
        payload["detail_values"].update(
            {
                "outcome": "[SKIPPED]",
                "intervention": "[CLEAR_IN_ORIGINAL]",
            }
        )
        response = QueryRefinementResponse(**payload)

        assert response.refined_dimensions["outcome"] == "[SKIPPED]"
        assert response.refined_dimensions["intervention"] == "[CLEAR_IN_ORIGINAL]"

    def test_model_allows_updates(self):
        """Test model configuration allows field updates."""
        response = QueryRefinementResponse(**self._base_payload())

        # Should allow updates (frozen=False in Config)
        response.synthesized_statement = "updated"
        assert response.synthesized_statement == "updated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
