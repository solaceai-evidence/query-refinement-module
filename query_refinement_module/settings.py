"""Runtime configuration helpers for the query refinement module."""

from __future__ import annotations

import copy
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
_ENV_ENABLE_PROMPT_CACHING = "QUERY_REFINEMENT_ENABLE_PROMPT_CACHING"
_ENV_ENABLE_CIRCUIT_BREAKER = "QUERY_REFINEMENT_ENABLE_CIRCUIT_BREAKER"
_ENV_CONSTRAINED_DECODING = "QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING"
_ENV_CIRCUIT_BREAKER_FAILURE_THRESHOLD = "QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD"
_ENV_CIRCUIT_BREAKER_RECOVERY_TIMEOUT = "QUERY_REFINEMENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT"
_ENV_RATE_LIMIT_RPM = "QUERY_REFINEMENT_LLM_RATE_LIMIT_RPM"
_ENV_RATE_LIMIT_TPM = "QUERY_REFINEMENT_LLM_RATE_LIMIT_TPM"
_ENV_MAX_CONCURRENT = "QUERY_REFINEMENT_LLM_MAX_CONCURRENT"
_ENV_ADAPTIVE_RATE_LIMIT = "QUERY_REFINEMENT_LLM_ADAPTIVE_RATE_LIMIT"


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


def _parse_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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


def _parse_bool(value: Optional[str], default: bool) -> bool:
    """Parse boolean from environment variable."""
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    elif normalized in ("false", "0", "no", "off"):
        return False
    else:
        return default  # For unrecognized values, use default


@dataclass
class LLMSettings:
    """Centralised configuration for the default LLM provider/analyzer stack."""

    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    completion_kwargs: Dict[str, Any] = field(default_factory=dict)
    enable_prompt_caching: bool = True
    enable_circuit_breaker: bool = True
    constrained_decoding: bool = False
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0
    terminal_reinforcement_threshold: int = 3  # Hardcoded optimal value (data-driven from 3,777 dimensions)
    # Rate limiting for proprietary LLM APIs (0 / None = unlimited)
    rate_limit_rpm: int = 0
    rate_limit_tpm: Optional[int] = None
    max_concurrent_requests: int = 20
    adaptive_rate_limit: bool = False

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
        api_key = _parse_optional_string(os.getenv(_ENV_API_KEY))
        api_base = _parse_optional_string(os.getenv(_ENV_API_BASE))
        temperature = _parse_float(os.getenv(_ENV_TEMPERATURE), default=0.0)
        max_tokens = _parse_int(os.getenv(_ENV_MAX_TOKENS))
        completion_kwargs = _parse_completion_kwargs(os.getenv(_ENV_COMPLETION_KWARGS))
        enable_prompt_caching = _parse_bool(os.getenv(_ENV_ENABLE_PROMPT_CACHING), default=True)
        enable_circuit_breaker = _parse_bool(os.getenv(_ENV_ENABLE_CIRCUIT_BREAKER), default=True)
        constrained_decoding = _parse_bool(os.getenv(_ENV_CONSTRAINED_DECODING), default=False)
        circuit_breaker_failure_threshold = _parse_int(os.getenv(_ENV_CIRCUIT_BREAKER_FAILURE_THRESHOLD, "5")) or 5
        circuit_breaker_recovery_timeout = float(os.getenv(_ENV_CIRCUIT_BREAKER_RECOVERY_TIMEOUT, "60.0"))
        rate_limit_rpm = _parse_int(os.getenv(_ENV_RATE_LIMIT_RPM, "0")) or 0
        rate_limit_tpm_raw = _parse_int(os.getenv(_ENV_RATE_LIMIT_TPM))
        max_concurrent_requests = _parse_int(os.getenv(_ENV_MAX_CONCURRENT, "20")) or 20
        adaptive_rate_limit = _parse_bool(os.getenv(_ENV_ADAPTIVE_RATE_LIMIT), default=False)

        return cls(
            model=model,
            api_key=api_key,
            api_base=api_base,
            temperature=temperature,
            max_tokens=max_tokens,
            completion_kwargs=completion_kwargs,
            enable_prompt_caching=enable_prompt_caching,
            enable_circuit_breaker=enable_circuit_breaker,
            constrained_decoding=constrained_decoding,
            circuit_breaker_failure_threshold=circuit_breaker_failure_threshold,
            circuit_breaker_recovery_timeout=circuit_breaker_recovery_timeout,
            # terminal_reinforcement_threshold uses class default of 3 (data-driven optimal value)
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_tpm=rate_limit_tpm_raw,
            max_concurrent_requests=max_concurrent_requests,
            adaptive_rate_limit=adaptive_rate_limit,
        )

    def as_provider_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``LiteLLMProvider`` construction."""
        from query_refinement_module.providers import CircuitBreakerConfig
        
        # Create circuit breaker config if enabled
        circuit_breaker_config = None
        if self.enable_circuit_breaker:
            circuit_breaker_config = CircuitBreakerConfig(
                failure_threshold=self.circuit_breaker_failure_threshold,
                recovery_timeout=self.circuit_breaker_recovery_timeout,
            )
        
        rate_limit_config = None
        if self.rate_limit_rpm > 0 or self.rate_limit_tpm is not None:
            from query_refinement_module.interfaces import RateLimitConfig
            rate_limit_config = RateLimitConfig(
                requests_per_minute=self.rate_limit_rpm,
                tokens_per_minute=self.rate_limit_tpm,
                max_concurrent_requests=self.max_concurrent_requests,
                adaptive_backoff=self.adaptive_rate_limit,
            )

        return {
            "default_model": self.model,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "default_completion_kwargs": copy.deepcopy(self.completion_kwargs),
            "enable_prompt_caching": self.enable_prompt_caching,
            "enable_circuit_breaker": self.enable_circuit_breaker,
            "constrained_decoding": self.constrained_decoding,
            "circuit_breaker_config": circuit_breaker_config,
            "rate_limit_config": rate_limit_config,
            "max_concurrent_requests": self.max_concurrent_requests,
        }

    def as_analyzer_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``LLMQueryAnalyzer`` construction."""

        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "completion_kwargs": copy.deepcopy(self.completion_kwargs),
        }


__all__ = ["LLMSettings"]
