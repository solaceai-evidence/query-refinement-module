"""Runtime configuration helpers for the query refinement module."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from query_refinement_module.llm_model_defaults import get_model_defaults


def _parse_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - configuration error surface
        raise ValueError(f"Invalid float value '{value}' for LLM configuration") from exc


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - configuration error surface
        raise ValueError(f"Invalid integer value '{value}' for LLM configuration") from exc


def _parse_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    return normalized or None


def _parse_completion_kwargs(raw: Optional[str] | Dict[str, Any]) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("LLM completion kwargs must be a JSON object mapping str -> value")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - configuration error surface
        raise ValueError(
            "LLM completion kwargs must contain valid JSON object"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM completion kwargs must be a JSON object mapping str -> value")
    return parsed


def _parse_bool(value: Optional[str], default: bool) -> bool:
    """Parse boolean from environment variable."""
    if isinstance(value, bool):
        return value
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    return default


class LLMSettings(BaseSettings):
    """Centralised configuration for the default LLM provider runtime."""

    model: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_MODEL", "QUERY_REFINEMENT_LLM_MODEL"),
    )
    api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "QUERY_REFINEMENT_LLM_API_KEY"),
    )
    api_base: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_BASE", "QUERY_REFINEMENT_LLM_API_BASE"),
    )
    temperature: float = Field(
        default=0.0,
        validation_alias=AliasChoices("LLM_TEMPERATURE", "QUERY_REFINEMENT_LLM_TEMPERATURE"),
    )
    max_tokens: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_MAX_OUTPUT_TOKENS", "QUERY_REFINEMENT_LLM_MAX_TOKENS"),
    )
    context_window: Optional[int] = Field(
        default=None,
        exclude=True,
        validation_alias=AliasChoices("LLM_CONTEXT_WINDOW", "QUERY_REFINEMENT_LLM_CONTEXT_WINDOW"),
    )
    completion_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("LLM_COMPLETION_KWARGS", "QUERY_REFINEMENT_LLM_COMPLETION_KWARGS"),
    )
    enable_prompt_caching: bool = Field(
        default=True,
        validation_alias=AliasChoices("LLM_ENABLE_PROMPT_CACHING", "QUERY_REFINEMENT_ENABLE_PROMPT_CACHING"),
    )
    enable_circuit_breaker: bool = Field(
        default=True,
        validation_alias=AliasChoices("LLM_ENABLE_CIRCUIT_BREAKER", "QUERY_REFINEMENT_ENABLE_CIRCUIT_BREAKER"),
    )
    constrained_decoding: bool = Field(
        default=False,
        validation_alias=AliasChoices("LLM_CONSTRAINED_DECODING", "QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING"),
    )
    circuit_breaker_failure_threshold: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
            "QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        ),
    )
    circuit_breaker_recovery_timeout: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "LLM_CIRCUIT_BREAKER_RECOVERY_TIMEOUT",
            "QUERY_REFINEMENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT",
        ),
    )
    terminal_reinforcement_threshold: int = 3
    rate_limit_rpm: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_RATE_LIMIT_RPM",
            "QUERY_REFINEMENT_LLM_RATE_LIMIT_RPM",
            "LLM_RATE_LIMIT_RPM",
        ),
    )
    rate_limit_tpm: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_RATE_LIMIT_TPM",
            "QUERY_REFINEMENT_LLM_RATE_LIMIT_TPM",
            "LLM_RATE_LIMIT_TPM",
        ),
    )
    max_concurrent_requests: int = Field(
        default=20,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_MAX_CONCURRENT",
            "QUERY_REFINEMENT_LLM_MAX_CONCURRENT",
            "LLM_MAX_CONCURRENT",
        ),
    )
    adaptive_rate_limit: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_ADAPTIVE_RATE_LIMIT",
            "QUERY_REFINEMENT_LLM_ADAPTIVE_RATE_LIMIT",
            "LLM_ADAPTIVE_RATE_LIMITING",
        ),
    )
    adaptive_decrease_factor: float = Field(
        default=0.8,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_ADAPTIVE_DECREASE_FACTOR",
            "LLM_ADAPTIVE_DECREASE_FACTOR",
        ),
    )
    adaptive_increase_factor: float = Field(
        default=1.05,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_ADAPTIVE_INCREASE_FACTOR",
            "LLM_ADAPTIVE_INCREASE_FACTOR",
        ),
    )
    adaptive_increase_interval: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "LLM_PROVIDER_ADAPTIVE_INCREASE_INTERVAL",
            "LLM_ADAPTIVE_INCREASE_INTERVAL",
        ),
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("model", "api_key", "api_base", mode="before")
    @classmethod
    def _normalize_string_inputs(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip()

    @field_validator("temperature", mode="before")
    @classmethod
    def _parse_temperature(cls, value: Any) -> float:
        return _parse_float(value, default=0.0)

    @field_validator("max_tokens", "context_window", "rate_limit_tpm", mode="before")
    @classmethod
    def _parse_optional_int_fields(cls, value: Any) -> Optional[int]:
        return _parse_int(value)

    @field_validator("completion_kwargs", mode="before")
    @classmethod
    def _parse_completion_kwargs_field(cls, value: Any) -> Dict[str, Any]:
        return _parse_completion_kwargs(value)

    @field_validator(
        "enable_prompt_caching",
        "enable_circuit_breaker",
        "constrained_decoding",
        "adaptive_rate_limit",
        mode="before",
    )
    @classmethod
    def _parse_bool_fields(cls, value: Any, info: Any) -> bool:
        default = cls.model_fields[info.field_name].default
        if isinstance(default, bool):
            return _parse_bool(value, default)
        return value

    @model_validator(mode="after")
    def _apply_model_defaults(self) -> "LLMSettings":
        fields_set = set(self.model_fields_set)
        explicit_api_base = _parse_optional_string(self.api_base)
        self.api_key = _parse_optional_string(self.api_key)

        model_defaults = get_model_defaults(self.model, api_base=explicit_api_base)
        if explicit_api_base is None:
            self.api_base = model_defaults.default_api_base
        else:
            self.api_base = explicit_api_base

        if self.max_tokens is None:
            self.max_tokens = model_defaults.default_max_tokens

        merged_completion_kwargs = copy.deepcopy(model_defaults.default_completion_kwargs)
        merged_completion_kwargs.update(copy.deepcopy(self.completion_kwargs))
        if model_defaults.default_timeout_seconds is not None:
            merged_completion_kwargs.setdefault("timeout", model_defaults.default_timeout_seconds)

        if self.context_window is not None:
            if model_defaults.context_window_kwarg is None:
                raise ValueError(
                    "QUERY_REFINEMENT_LLM_CONTEXT_WINDOW / LLM_CONTEXT_WINDOW is not supported for model "
                    f"'{self.model}'. Use LLM_COMPLETION_KWARGS only for backends "
                    "that expose a client-side context size control."
                )
            if model_defaults.context_window_kwarg not in self.completion_kwargs:
                merged_completion_kwargs[model_defaults.context_window_kwarg] = self.context_window

        self.completion_kwargs = merged_completion_kwargs

        default_rate_limit = model_defaults.rate_limit
        if model_defaults.family != "unknown" and "enable_prompt_caching" not in fields_set:
            self.enable_prompt_caching = model_defaults.prompt_caching

        if "rate_limit_rpm" not in fields_set:
            self.rate_limit_rpm = (
                default_rate_limit.requests_per_minute if default_rate_limit is not None else 0
            )
        if "rate_limit_tpm" not in fields_set:
            self.rate_limit_tpm = (
                default_rate_limit.tokens_per_minute if default_rate_limit is not None else None
            )
        if "max_concurrent_requests" not in fields_set:
            self.max_concurrent_requests = (
                default_rate_limit.max_concurrent_requests
                if default_rate_limit is not None and default_rate_limit.max_concurrent_requests > 0
                else 20
            )
        if "adaptive_rate_limit" not in fields_set:
            self.adaptive_rate_limit = (
                default_rate_limit.adaptive_backoff if default_rate_limit is not None else False
            )

        return self

    @classmethod
    def from_env(
        cls,
        *,
        require_model: bool = True,
        load_env_file: bool = False,
    ) -> "LLMSettings":
        """Load LLM settings from environment variables."""
        if load_env_file:
            from dotenv import load_dotenv

            load_dotenv(override=False)

        settings = cls()
        if require_model and not settings.model:
            raise RuntimeError(
                "Environment variable LLM_MODEL (or QUERY_REFINEMENT_LLM_MODEL) "
                "must be set to the default model id."
            )
        return settings

    def as_provider_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``LiteLLMProvider`` construction."""
        from query_refinement_module.providers import CircuitBreakerConfig

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
                adaptive_decrease_factor=self.adaptive_decrease_factor,
                adaptive_increase_factor=self.adaptive_increase_factor,
                adaptive_increase_interval=self.adaptive_increase_interval,
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