"""Analyzer implementations for determining refinement needs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from .interfaces import (
    AspectAnalysisResult,
    LLMProviderInterface,
    QueryAnalyzerInterface,
)

__all__ = ["LLMQueryAnalyzer"]

logger = logging.getLogger(__name__)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMQueryAnalyzer(QueryAnalyzerInterface):
    """LLM-driven analyzer that uses aspect prompts to detect refinement gaps."""

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        *,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        completion_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._llm = llm_provider
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._completion_kwargs = completion_kwargs or {}

    def analyze_aspect(
        self,
        query: str,
        aspect,
        dependency_context: Optional[Dict[str, str]] = None,
        llm_provider: Optional[LLMProviderInterface] = None,
    ) -> AspectAnalysisResult:
        provider = llm_provider or self._llm
        if provider is None:
            raise ValueError("LLM provider must be supplied to analyze aspects")

        system_prompt = aspect.get_system_prompt()
        user_prompt = self._build_prompt(query, aspect, dependency_context)

        dependency_keys = sorted(dependency_context.keys()) if dependency_context else []
        logger.info(
            "Analyzer prompt dispatched | aspect=%s | dependency_keys=%s | system_prompt=%s | user_prompt=%s",
            aspect.id,
            dependency_keys,
            system_prompt or "",
            user_prompt,
        )

        result = provider.complete(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **self._completion_kwargs,
        )

        payload = self._parse_payload(result.context)
        if payload is None:
            logger.warning(
                "Failed to parse analyzer response for aspect '%s'. Falling back to manual refinement.",
                aspect.id,
            )
            return AspectAnalysisResult(
                needs_refinement=True,
                explanation="Unable to parse analyzer response; requesting manual clarification.",
                clarifying_question=aspect.aspect_name,
            )

        if "needs_refinement" not in payload:
            logger.warning(
                "Analyzer response for aspect '%s' missing 'needs_refinement'; defaulting to manual refinement.",
                aspect.id,
            )
            return AspectAnalysisResult(
                needs_refinement=True,
                explanation="Analyzer response missing required 'needs_refinement' field.",
                clarifying_question=aspect.aspect_name,
            )

        needs_refinement = self._coerce_bool(payload["needs_refinement"])
        explanation = payload.get("explanation") or ""
        clarifying_question = payload.get("clarifying_question")

        if needs_refinement:
            if not clarifying_question:
                logger.warning(
                    "Analyzer response for aspect '%s' missing 'clarifying_question'. Using aspect name as fallback.",
                    aspect.id,
                )
                clarifying_question = aspect.aspect_name

        return AspectAnalysisResult(
            needs_refinement=needs_refinement,
            explanation=explanation,
            clarifying_question=clarifying_question,
        )

    def _build_prompt(
        self,
        query: str,
        aspect,
        dependency_context: Optional[Dict[str, str]] = None,
    ) -> str:
        prompt_sections = []

        if dependency_context:
            lines = ["Dependency context:"]
            for dep_id, value in sorted(dependency_context.items()):
                lines.append(f"- {dep_id}: {value}")
            prompt_sections.append("\n".join(lines))

        prompt_sections.append(aspect.get_refinement_instructions_prompt(statement=query))
        return "\n\n".join(prompt_sections)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered in {"true", "1", "yes", "y"}
        return True

    def _parse_payload(self, raw_text: str) -> Optional[Dict[str, Any]]:
        candidate = raw_text.strip()
        if not candidate:
            return None

        if candidate.startswith("```"):
            candidate = self._strip_code_fence(candidate)

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(candidate)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _strip_code_fence(payload: str) -> str:
        lines = payload.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            # Drop opening fence and optional closing fence
            body = lines[1:]
            if body and body[-1].startswith("```"):
                body = body[:-1]
            return "\n".join(body)
        return payload
