"""Runtime configuration helpers for the query refinement module."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_ENV_MODEL = "QUERY_REFINEMENT_LLM_MODEL"
_ENV_API_KEY = "QUERY_REFINEMENT_LLM_API_KEY"
_ENV_API_BASE = "QUERY_REFINEMENT_LLM_API_BASE"
_ENV_TEMPERATURE = "QUERY_REFINEMENT_LLM_TEMPERATURE"
_ENV_MAX_TOKENS = "QUERY_REFINEMENT_LLM_MAX_TOKENS"
_ENV_COMPLETION_KWARGS = "QUERY_REFINEMENT_LLM_COMPLETION_KWARGS"


def _parse_float(value: Optional[str], default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:  # pragma: no cover - configuration error surface
        raise ValueError(f"Invalid float value '{value}' for LLM configuration") from exc


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - configuration error surface
        raise ValueError(f"Invalid integer value '{value}' for LLM configuration") from exc


def _parse_completion_kwargs(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - configuration error surface
        raise ValueError(
            "QUERY_REFINEMENT_LLM_COMPLETION_KWARGS must contain valid JSON object"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM completion kwargs must be a JSON object mapping str -> value")
    return parsed


@dataclass
class LLMSettings:
    """Centralised configuration for the default LLM provider/analyzer stack."""

    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    completion_kwargs: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, *, require_model: bool = True) -> "LLMSettings":
        """Load LLM settings from environment variables.

        Raises:
            RuntimeError: if no model is provided and ``require_model`` is True.
            ValueError: if any value cannot be coerced into the expected type.
        """

        model = os.getenv(_ENV_MODEL, "").strip()
        if not model:
            if require_model:
                raise RuntimeError(
                    f"Environment variable {_ENV_MODEL} must be set to the default model id."
                )
        api_key = os.getenv(_ENV_API_KEY)
        api_base = os.getenv(_ENV_API_BASE)
        temperature = _parse_float(os.getenv(_ENV_TEMPERATURE), default=0.0)
        max_tokens = _parse_int(os.getenv(_ENV_MAX_TOKENS))
        completion_kwargs = _parse_completion_kwargs(os.getenv(_ENV_COMPLETION_KWARGS))

        return cls(
            model=model,
            api_key=api_key,
            api_base=api_base,
            temperature=temperature,
            max_tokens=max_tokens,
            completion_kwargs=completion_kwargs,
        )

    def as_provider_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``LiteLLMProvider`` construction."""

        return {
            "default_model": self.model,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "default_completion_kwargs": self.completion_kwargs,
        }

    def as_analyzer_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``LLMQueryAnalyzer`` construction."""

        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "completion_kwargs": self.completion_kwargs,
        }


__all__ = ["LLMSettings"]
