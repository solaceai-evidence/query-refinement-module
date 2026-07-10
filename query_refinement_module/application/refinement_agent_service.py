"""Agent-oriented refinement workflows."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.schema.response import SearchExpansionInput

from .refinement_service_support import RefinementServiceSupport
from .refinement_workflow import is_session_ready_for_synthesis


logger = logging.getLogger(__name__)


class RefinementAgentService:
    """Owns the agent-style transforms that operate on refined statements."""

    def __init__(self, support: RefinementServiceSupport) -> None:
        self._support = support

    async def normalize_workflow(
        self,
        *,
        query_id: int,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._support.get_framework_or_raise(framework_name)

        try:
            async with self._support.session_manager.session_lock(query_id):
                session = await self._support.load_or_reconstruct_session(
                    query_id=query_id,
                    db_query=db_query,
                    framework=framework,
                )
                if not is_session_ready_for_synthesis(session):
                    raise QueryRefinementException(
                        "Query is not ready for normalization. Complete all dimensions or use /submit first.",
                        status_code=409,
                    )

                norm, _ = await self._support.manager._run_normalization(session)
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d during normalization: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

        logger.info(
            "API: Agent A completed",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "clarified_query_length": len(norm.clarified_query),
            },
        )
        return {
            "query_id": query_id,
            "clarified_query": norm.clarified_query,
            "dimensions_specifications": norm.dimensions_specifications,
            "used_llm": True,
        }

    async def represent_workflow(
        self,
        *,
        statement: str,
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        logger.info(
            "API: Running Agent B (Semantic Representation)",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "statement_length": len(statement),
            },
        )

        try:
            sem, _ = await self._support.manager._run_semantic_representation(
                statement,
                model=model,
            )
        except Exception as exc:
            logger.exception("API: Agent B failed", extra={"request_id": request_id})
            raise QueryRefinementException(
                f"Semantic representation failed: {exc}",
                status_code=500,
            ) from exc

        concept_graph_dict = {
            key: (value.model_dump() if hasattr(value, "model_dump") else value)
            for key, value in sem.concept_graph.items()
        }
        return {
            "semantic_statement": sem.semantic_statement,
            "keyword_statement": sem.keyword_statement,
            "concept_graph": concept_graph_dict,
            "used_llm": True,
        }

    async def construct_workflow(
        self,
        *,
        statement: str,
        concept_graph: Dict[str, Any],
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        logger.info(
            "API: Running Agent C (Search Construction)",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "statement_length": len(statement),
                "concept_graph_size": len(concept_graph),
            },
        )

        try:
            construction, _ = await self._support.manager._run_search_construction(
                statement=statement,
                concept_graph=concept_graph,
                model=model,
            )
        except Exception as exc:
            logger.exception("API: Agent C failed", extra={"request_id": request_id})
            raise QueryRefinementException(
                f"Search construction failed: {exc}",
                status_code=500,
            ) from exc

        keyword_dict = construction.keyword.model_dump() if hasattr(construction.keyword, "model_dump") else construction.keyword
        filters_dict = construction.search_filters.model_dump() if hasattr(construction.search_filters, "model_dump") else construction.search_filters
        return {
            "keyword": keyword_dict,
            "search_filters": filters_dict,
            "used_llm": True,
        }

    async def expand_workflow(
        self,
        *,
        statement: str,
        anchor_blocks,
        search_context,
        semantic_statement: Optional[str],
        keyword_statement: Optional[str],
        keyword_structured: Optional[str],
        search_filters,
        phrases,
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        concept_graph = {}
        if search_context and search_context.concept_graph:
            concept_graph = search_context.concept_graph

        logger.info(
            "API: Generating search expansion levels",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "model_override": model,
                "statement_length": len(statement),
                "anchor_block_count": len(anchor_blocks),
            },
        )

        try:
            expansion_input = SearchExpansionInput(
                clarified_query=statement,
                anchor_blocks=anchor_blocks,
                concept_graph=concept_graph,
                semantic_statement=semantic_statement or "",
                keyword_statement=keyword_statement or "",
                keyword_structured=keyword_structured or "",
                search_filters=search_filters,
                phrases=phrases or [],
            )
            result, metadata = await self._support.manager.generate_search_expansion_levels(
                search_input=expansion_input,
                model=model,
            )
        except Exception as exc:
            logger.exception(
                "API: Search expansion generation failed unexpectedly",
                extra={"request_id": request_id, "error": str(exc)},
            )
            raise QueryRefinementException(
                f"Failed to generate search expansion levels: {str(exc)}",
                status_code=500,
            ) from exc

        levels_payload = [level.model_dump(by_alias=True) for level in result.levels]
        metadata["geography_broadening_strategy"] = result.geography_broadening_strategy
        metadata["recommended_starting_level"] = result.recommended_starting_level
        metadata["recommendation_rationale"] = result.recommendation_rationale
        if result.search_filters:
            metadata["search_filters"] = (
                result.search_filters.model_dump()
                if hasattr(result.search_filters, "model_dump")
                else result.search_filters
            )
        if result.phrases:
            metadata["phrases"] = result.phrases

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Search expansion completed",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
                "returned_level_count": len(levels_payload),
                "generated_level_count": metadata.get("generated_level_count", 0),
                "status": metadata.get("status"),
            },
        )

        return {
            "levels": levels_payload,
            "geography_broadening_strategy": result.geography_broadening_strategy,
            "recommended_starting_level": result.recommended_starting_level,
            "recommendation_rationale": result.recommendation_rationale,
            "search_filters": (
                result.search_filters.model_dump()
                if hasattr(result.search_filters, "model_dump")
                else result.search_filters
            ) if result.search_filters else None,
            "phrases": result.phrases or None,
            "metadata": metadata,
        }