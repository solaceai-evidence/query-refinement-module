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
        """Base payload using LLM field names (as template specifies)."""
        return {
            "clarified_query": "diabetes in adults",
            "dimensions_specifications": {"population": "adults", "condition": "diabetes"},
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
                "venues": [],
                "authors": [],
                "publication_types": [],
                "fields_of_study": [],
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
    
    def _minimal_payload(self):
        """Minimal payload with only required fields using LLM field names."""
        return {
            "clarified_query": "diabetes in adults",
            "dimensions_specifications": {"population": "adults", "condition": "diabetes"},
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
                # grey_literature is optional - omitted
            },
            "search_filters": {
                "publication_years": "",
                "venues": [],
                "authors": [],
                "publication_types": [],
                "fields_of_study": [],
            },
            "terminology": {
                # primary_terms is optional - omitted
                "synonyms": {"diabetes": ["T2DM"]},
                # domain_specific is optional - omitted
                "colloquial": [],
            },
            # metadata is optional - omitted
            # processing_log is optional - omitted
        }

    def test_valid_minimal_response(self):
        """Test creation with minimal required fields."""
        response = QueryRefinementResponse(**self._base_payload())

        # Verify Python code accesses via LLM template field names
        assert response.clarified_query == "diabetes in adults"
        assert response.dimensions_specifications == {"population": "adults", "condition": "diabetes"}
        assert response.search_filters.publication_years == ""

    def test_valid_response_with_all_fields(self):
        """Test creation with all optional fields."""
        payload = self._base_payload()
        payload["clarified_query"] = "diabetes treatment in adults"
        payload["dimensions_specifications"].update(
            {
                "intervention": "metformin",
                "outcome": "glycemic control",
            }
        )
        payload["search_filters"].update(
            {
                "publication_years": "2018-2023",
                "venues": ["Diabetes Care", "JAMA"],
                "authors": ["Smith J", "Johnson M"],
                "fields_of_study": ["Medicine", "Endocrinology"],
            }
        )

        response = QueryRefinementResponse(**payload)

        # Access via LLM template field names
        assert response.clarified_query == "diabetes treatment in adults"
        assert response.search_filters.publication_years == "2018-2023"
        assert response.search_filters.venues == ["Diabetes Care", "JAMA"]
        assert len(response.search_filters.authors) == 2
        assert response.search_filters.fields_of_study == ["Medicine", "Endocrinology"]

    def test_missing_required_field_clarified_query(self):
        """Test validation fails without clarified_query (LLM field name)."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload.pop("clarified_query")
            QueryRefinementResponse(**payload)
        
        # Validation should fail - check that at least one error occurred
        errors = exc_info.value.errors()
        assert len(errors) > 0

    def test_missing_required_field_dimensions_specifications(self):
        """Test validation fails without dimensions_specifications (LLM field name)."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload.pop("dimensions_specifications")
            QueryRefinementResponse(**payload)
        
        # Validation should fail - check that at least one error occurred
        errors = exc_info.value.errors()
        assert len(errors) > 0

    def test_dimensions_specifications_must_be_dict(self):
        """Test dimensions_specifications must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            payload = self._base_payload()
            payload["dimensions_specifications"] = "not a dict"
            QueryRefinementResponse(**payload)
        
        errors = exc_info.value.errors()
        assert any("dimensions_specifications" in str(e["loc"]) for e in errors)

    def test_default_empty_values(self):
        """Test default values for optional fields."""
        response = QueryRefinementResponse(**self._base_payload())

        assert response.search_filters.publication_years == ""
        assert response.search_filters.venues == []
        assert response.search_filters.authors == []
        assert response.search_filters.fields_of_study == []

    def test_dimensions_specifications_with_special_values(self):
        """Test dimensions_specifications can contain special markers like [SKIPPED] and actual values."""
        payload = self._base_payload()
        payload["dimensions_specifications"].update(
            {
                "outcome": "[SKIPPED]",
                "intervention": "metformin 500mg daily",
            }
        )
        response = QueryRefinementResponse(**payload)

        # Access via LLM template field names
        assert response.dimensions_specifications["outcome"] == "[SKIPPED]"
        assert response.dimensions_specifications["intervention"] == "metformin 500mg daily"

    def test_model_allows_updates(self):
        """Test model configuration allows field updates."""
        response = QueryRefinementResponse(**self._base_payload())

        # Should allow updates (frozen=False in Config)
        response.clarified_query = "updated"
        assert response.clarified_query == "updated"
    
    def test_optional_fields_can_be_omitted(self):
        """Test that optional fields (grey_literature, primary_terms, domain_specific, metadata, processing_log) can be omitted."""
        payload = self._minimal_payload()
        response = QueryRefinementResponse(**payload)
        
        # Verify required fields are present
        assert response.clarified_query == "diabetes in adults"
        assert response.dimensions_specifications == {"population": "adults", "condition": "diabetes"}
        assert response.search_optimized.semantic
        assert response.search_optimized.keyword
        
        # Verify optional fields are None when omitted
        assert response.search_optimized.grey_literature is None
        assert response.terminology.primary_terms is None
        assert response.terminology.domain_specific is None
        assert response.metadata is None
        assert response.processing_log is None
        
        # Verify other fields still work
        assert response.terminology.synonyms == {"diabetes": ["T2DM"]}
        assert response.terminology.colloquial == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
