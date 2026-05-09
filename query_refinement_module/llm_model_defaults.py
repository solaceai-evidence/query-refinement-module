"""Shared model-family defaults for LLM configuration.

These defaults are intentionally conservative. They are used only when the user
does not provide an explicit environment override.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .interfaces import RateLimitConfig

DEFAULT_OLLAMA_API_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_NUM_CTX = 16384
DEFAULT_PROPRIETARY_MAX_TOKENS = 4096


@dataclass(frozen=True)
class LLMModelDefaults:
    family: str
    prompt_caching: bool = False
    default_api_base: Optional[str] = None
    default_completion_kwargs: Dict[str, Any] = field(default_factory=dict)
    default_max_tokens: Optional[int] = None
    rate_limit: Optional[RateLimitConfig] = None
    context_window_kwarg: Optional[str] = None


def normalize_model(model: str) -> str:
    return model.strip().lower()


def _is_openai_model(model: str) -> bool:
    normalized = normalize_model(model)
    return (
        normalized.startswith("openai/")
        or normalized.startswith("gpt-")
        or normalized.startswith("o1")
        or normalized.startswith("o3")
        or normalized.startswith("o4")
    )


def _is_anthropic_model(model: str) -> bool:
    normalized = normalize_model(model)
    return normalized.startswith("anthropic/") or normalized.startswith("claude-")


def _is_ollama_model(model: str) -> bool:
    return normalize_model(model).startswith("ollama/")


def _is_gemini_model(model: str) -> bool:
    normalized = normalize_model(model)
    return normalized.startswith("gemini-") or normalized.startswith("google/")


def _uses_openai_compatible_endpoint(model: str, api_base: Optional[str]) -> bool:
    return bool(api_base) and _is_openai_model(model)


def get_model_defaults(model: str, api_base: Optional[str] = None) -> LLMModelDefaults:
    normalized = normalize_model(model)

    if _is_anthropic_model(normalized):
        return LLMModelDefaults(
            family="anthropic",
            prompt_caching=True,
            default_max_tokens=DEFAULT_PROPRIETARY_MAX_TOKENS,
            rate_limit=RateLimitConfig(
                requests_per_minute=50,
                tokens_per_minute=40000,
                max_concurrent_requests=5,
            ),
        )

    if _uses_openai_compatible_endpoint(normalized, api_base):
        return LLMModelDefaults(
            family="openai-compatible",
            default_max_tokens=DEFAULT_PROPRIETARY_MAX_TOKENS,
            rate_limit=RateLimitConfig.unlimited(),
        )

    if _is_openai_model(normalized):
        is_high_end = "gpt-4" in normalized or "gpt-4o" in normalized or normalized.startswith(("o1", "o3", "o4"))
        return LLMModelDefaults(
            family="openai",
            default_max_tokens=DEFAULT_PROPRIETARY_MAX_TOKENS,
            rate_limit=(
                RateLimitConfig(
                    requests_per_minute=500,
                    tokens_per_minute=30000,
                    max_concurrent_requests=10,
                )
                if is_high_end
                else RateLimitConfig(
                    requests_per_minute=3500,
                    tokens_per_minute=90000,
                    max_concurrent_requests=10,
                )
            ),
        )

    if _is_gemini_model(normalized):
        return LLMModelDefaults(
            family="google",
            default_max_tokens=DEFAULT_PROPRIETARY_MAX_TOKENS,
            rate_limit=RateLimitConfig(
                requests_per_minute=60,
                tokens_per_minute=32000,
                max_concurrent_requests=5,
            ),
        )

    if _is_ollama_model(normalized) or "llama" in normalized:
        return LLMModelDefaults(
            family="ollama",
            default_api_base=DEFAULT_OLLAMA_API_BASE,
            default_completion_kwargs={"num_ctx": DEFAULT_OLLAMA_NUM_CTX},
            default_max_tokens=DEFAULT_PROPRIETARY_MAX_TOKENS,
            rate_limit=RateLimitConfig.unlimited(),
            context_window_kwarg="num_ctx",
        )

    return LLMModelDefaults(family="unknown")


__all__ = [
    "DEFAULT_OLLAMA_API_BASE",
    "DEFAULT_OLLAMA_NUM_CTX",
    "DEFAULT_PROPRIETARY_MAX_TOKENS",
    "LLMModelDefaults",
    "get_model_defaults",
    "normalize_model",
]