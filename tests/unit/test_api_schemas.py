from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from query_refinement_module.api.schemas import QueryResponse


def test_query_response_uses_canonical_fields_for_orm_objects():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id=1,
        session_id=2,
        original_query="migraine prevention strategies",
        refined_query="legacy refined text",
        created_at=now,
        updated_at=now,
        completed_at=now,
        integrated_statement="Integrated migraine prevention statement",
        dimensions_specifications={"population": "Adults"},
        search_optimized={"semantic": "migraine prevention adults"},
        search_filters={"publication_types": ["Systematic review"]},
        terminology={"synonyms": {"migraine": ["headache disorder"]}},
        synthesis_metadata={"total_tokens": 123},
        processing_log={"preserved": ["population"]},
    )

    response = QueryResponse.from_query_record(row)
    dumped = response.model_dump()

    assert dumped["integrated_statement"] == "Integrated migraine prevention statement"
    assert dumped["dimensions_specifications"] == {"population": "Adults"}
    assert dumped["metadata"] == {"total_tokens": 123}
    assert "synthesized_statement" not in dumped
    assert "refined_dimensions" not in dumped
    assert "response_metadata" not in dumped


def test_query_response_accepts_canonical_keys_only():
    now = datetime.now(timezone.utc)
    response = QueryResponse.model_validate(
        {
            "id": 1,
            "session_id": 2,
            "original_query": "migraine prevention strategies",
            "refined_query": "legacy refined text",
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
            "integrated_statement": "Integrated migraine prevention statement",
            "dimensions_specifications": {"population": "Adults"},
            "search_optimized": {"semantic": "migraine prevention adults"},
            "search_filters": {"publication_types": ["Systematic review"]},
            "terminology": {"synonyms": {"migraine": ["headache disorder"]}},
            "metadata": {"total_tokens": 123},
            "processing_log": {"preserved": ["population"]},
        }
    )

    dumped = response.model_dump()

    assert dumped["integrated_statement"] == "Integrated migraine prevention statement"
    assert dumped["dimensions_specifications"] == {"population": "Adults"}
    assert dumped["metadata"] == {"total_tokens": 123}
    assert "synthesized_statement" not in dumped
    assert "refined_dimensions" not in dumped
    assert "response_metadata" not in dumped


def test_query_response_rejects_legacy_keys():
    now = datetime.now(timezone.utc)

    with pytest.raises(Exception):
        QueryResponse.model_validate(
            {
                "id": 1,
                "session_id": 2,
                "original_query": "migraine prevention strategies",
                "refined_query": "legacy refined text",
                "created_at": now,
                "updated_at": now,
                "completed_at": now,
                "synthesized_statement": "Integrated migraine prevention statement",
                "refined_dimensions": {"population": "Adults"},
                "search_optimized": {"semantic": "migraine prevention adults"},
                "search_filters": {"publication_types": ["Systematic review"]},
                "terminology": {"synonyms": {"migraine": ["headache disorder"]}},
                "response_metadata": {"total_tokens": 123},
                "processing_log": {"preserved": ["population"]},
            }
        )