"""
LLM provider implementations.

Extracted from providers.py as part of v2.0.0 Phase 4 refactoring.
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Type, Union

from query_refinement_module.tracing import get_request_id, get_trace_id
from query_refinement_module.llm_model_defaults import get_model_defaults

from ..interfaces import LLMCompletionResult, LLMProviderInterface, RateLimitConfig, RateLimitExceeded
from .circuit_breaker import CircuitBreakerRegistry, CircuitBreakerConfig, CircuitBreakerOpen
from ..rate_limiter import TokenBucketRateLimiter

# Optional dependencies
try:
    import litellm
except ImportError:
    litellm = None

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger(__name__)


class LiteLLMProvider(LLMProviderInterface):
    """Generic LLM provider backed by `litellm` for multi-vendor support with circuit breaker protection."""

    def __init__(
        self,
        default_model: str,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        default_completion_kwargs: Optional[Dict[str, Any]] = None,
        enable_prompt_caching: bool = True,
        enable_circuit_breaker: bool = True,
        constrained_decoding: bool = False,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        max_concurrent_requests: Optional[int] = None,
    ) -> None:
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        if not default_model:
            raise ValueError("default_model must be provided for LiteLLMProvider")

        self._default_model = default_model
        self._api_key = api_key
        self._api_base = api_base
        self._default_completion_kwargs = default_completion_kwargs or {}
        self._enable_prompt_caching = enable_prompt_caching
        self._constrained_decoding = constrained_decoding

        provider_defaults = self.get_rate_limits(default_model, api_base=api_base)
        resolved_max_concurrent = max_concurrent_requests
        if resolved_max_concurrent is None:
            if provider_defaults.max_concurrent_requests > 0:
                resolved_max_concurrent = provider_defaults.max_concurrent_requests
            else:
                resolved_max_concurrent = 20

        # Semaphore to limit concurrent LLM calls (prevent overwhelming server)
        self._max_concurrent = resolved_max_concurrent
        self._semaphore = asyncio.Semaphore(resolved_max_concurrent)
        
        # Token-bucket rate limiter for proprietary LLM APIs (Anthropic, OpenAI, etc.)
        # If no explicit config is provided, use provider defaults only when RPM > 0.
        if rate_limit_config is None:
            rate_limit_config = provider_defaults if provider_defaults.requests_per_minute > 0 else None

        self._rate_limiter: Optional[TokenBucketRateLimiter] = None
        if rate_limit_config is not None and rate_limit_config.requests_per_minute > 0:
            self._rate_limiter = TokenBucketRateLimiter(rate_limit_config, scope="global")
            logger.info(
                "LLM rate limiter enabled: rpm=%d, tpm=%s, adaptive=%s",
                rate_limit_config.requests_per_minute,
                rate_limit_config.tokens_per_minute,
                rate_limit_config.adaptive_backoff,
            )
        else:
            logger.debug(
                "LLM rate limiter disabled (unlimited). "
                "Set LLM_RATE_LIMIT_RPM to enable or override provider throttling."
            )

        # Circuit breaker for protecting against provider outages
        self._enable_circuit_breaker = enable_circuit_breaker
        if enable_circuit_breaker:
            # Configure circuit breaker to exclude rate limit errors
            # (rate limits are temporary throttling, not service outages)
            cb_config = circuit_breaker_config or CircuitBreakerConfig()
            
            # Define exceptions that should trigger circuit breaker
            # Excludes: RateLimitExceeded (temporary throttling)
            # Includes: TimeoutError, ConnectionError, 5xx errors, etc.
            cb_config.counted_exceptions = (
                TimeoutError,
                ConnectionError,
                RuntimeError,  # LiteLLM uses RuntimeError for API errors
                # Note: RateLimitExceeded is explicitly NOT included
            )
            
            self._circuit_breaker_registry = CircuitBreakerRegistry(cb_config)
            
            logger.info(
                "Circuit breaker enabled for LLM provider",
                extra={
                    "failure_threshold": cb_config.failure_threshold,
                    "recovery_timeout": cb_config.recovery_timeout,
                }
            )
        else:
            self._circuit_breaker_registry = None
        
        # Initialize persistent HTTP client for connection pooling (if httpx available)
        self._http_client: Optional[Any] = None
        if httpx is not None:
            self._http_client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=40,   
                    max_keepalive_connections=20, 
                    keepalive_expiry=30.0,
                ),
                timeout=httpx.Timeout(60.0),
            )
            logger.debug("Initialized HTTP connection pool for LiteLLM provider (max_connections=40)")
    
    def _extract_provider_from_model(self, model: str) -> str:
        """
        Extract provider name from model string for circuit breaker tracking.
        
        Args:
            model: Model identifier (e.g., "gpt-4", "claude-3-opus", "gemini-pro")
            
        Returns:
            Provider name (e.g., "openai", "anthropic", "google")
        """
        model_lower = model.lower()
        
        # Common provider patterns
        if "gpt" in model_lower or "o1" in model_lower or "text-davinci" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "gemini" in model_lower or "palm" in model_lower:
            return "google"
        elif "llama" in model_lower:
            return "meta"
        elif "mistral" in model_lower or "mixtral" in model_lower:
            return "mistral"
        elif "command" in model_lower:
            return "cohere"
        elif "bedrock" in model_lower:
            return "aws-bedrock"
        elif "azure" in model_lower:
            return "azure"
        else:
            # Use model prefix as provider name (handles custom models)
            return model.split("/")[0] if "/" in model else "unknown"

    async def complete_async(self, *args, **kwargs) -> "LLMCompletionResult":
        """Complete a prompt asynchronously with automatic retry on rate limit errors.
        
        Args:
            user_prompt: The user prompt (used if messages not provided)
            system_prompt: System prompt (used if messages not provided)
            messages: Full conversation history (takes precedence over prompts)
            response_format: Structured output format (Pydantic model or dict)
            cache_system_prompt: If True and provider supports it, cache the system prompt
                               for reduced token usage and faster responses.
        """
        # Apply outbound rate limit before acquiring the concurrency semaphore
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        # Apply semaphore to limit concurrent calls
        async with self._semaphore:
            return await self._complete_async_internal(*args, **kwargs)
    
    async def _complete_async_internal(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        cache_system_prompt: bool = False,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Union[Dict[str, Any], Type["BaseModel"]]] = None,
        **kwargs: Any,
    ) -> LLMCompletionResult:
        """Internal completion logic with retry and rate limit handling."""
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        target_model = model or self._default_model
        if not target_model:
            raise ValueError("Model must be supplied either at initialization or call time")

        # Build messages array
        if messages:
            # Use provided conversation history and apply caching to marked messages
            messages_list = []
            for msg in messages:
                new_msg = {"role": msg["role"], "content": msg["content"]}
                
                # Apply cache control if message is marked for caching
                if msg.get("_cache") and cache_system_prompt and self._enable_prompt_caching:
                    try:
                        new_msg["cache_control"] = {"type": "ephemeral"}
                        logger.debug(
                            "System message caching enabled for %s message",
                            msg["role"],
                            extra={
                                "model": target_model,
                                "content_preview": msg["content"][:50] + "...",
                                "request_id": get_request_id(),
                                "trace_id": get_trace_id(),
                            }
                        )
                    except Exception as e:
                        # Gracefully handle providers that don't support caching
                        logger.debug(
                            "Could not apply prompt caching (provider may not support it): %s",
                            e,
                            extra={"model": target_model}
                        )
                
                messages_list.append(new_msg)
        else:
            # Build from prompts (legacy path)
            messages_list = []
            if system_prompt:
                system_message = {"role": "system", "content": system_prompt}
                # Add cache control if enabled and requested
                if cache_system_prompt and self._enable_prompt_caching:
                    try:
                        system_message["cache_control"] = {"type": "ephemeral"}
                        logger.debug(
                            "System prompt caching enabled",
                            extra={
                                "model": target_model,
                                "request_id": get_request_id(),
                                "trace_id": get_trace_id(),
                            }
                        )
                    except Exception as e:
                        # Gracefully handle providers that don't support caching
                        logger.debug(
                            "Could not apply prompt caching (provider may not support it): %s",
                            e,
                            extra={"model": target_model}
                        )
                messages_list.append(system_message)
            if user_prompt:
                messages_list.append({"role": "user", "content": user_prompt})

        completion_kwargs: Dict[str, Any] = {**self._default_completion_kwargs, **kwargs}
        completion_kwargs.setdefault("temperature", temperature)
        if max_tokens is not None and "max_tokens" not in completion_kwargs:
            completion_kwargs["max_tokens"] = max_tokens
        
        # Get current request context for tracing (needed for logging below)
        request_id = get_request_id()
        trace_id = get_trace_id()
        
        # Handle response_format for structured outputs.
        # When constrained_decoding is enabled (vLLM), swap litellm's response_format
        # mechanism for vLLM's native guided_json via extra_body.
        _constrained_parse_model = None
        if response_format is not None:
            try:
                from pydantic import BaseModel
                if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                    if self._constrained_decoding:
                        # vLLM path: derive JSON Schema and pass as guided_json
                        schema = response_format.model_json_schema(by_alias=True)
                        _constrained_parse_model = response_format
                        existing_extra = completion_kwargs.get("extra_body", {})
                        completion_kwargs["extra_body"] = {**existing_extra, "guided_json": schema}
                        logger.debug(
                            "Using vLLM guided_json constrained decoding",
                            extra={
                                "model": target_model,
                                "response_format_type": response_format.__name__,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
                    else:
                        # Standard path: pass Pydantic model directly to litellm
                        completion_kwargs["response_format"] = response_format
                        logger.debug(
                            "Using Pydantic model for structured output",
                            extra={
                                "model": target_model,
                                "response_format_type": response_format.__name__,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
                elif isinstance(response_format, dict):
                    if (
                        self._constrained_decoding
                        and ("properties" in response_format or "$defs" in response_format)
                    ):
                        # Real JSON Schema dict — use as guided_json
                        existing_extra = completion_kwargs.get("extra_body", {})
                        completion_kwargs["extra_body"] = {**existing_extra, "guided_json": response_format}
                        logger.debug(
                            "Using vLLM guided_json constrained decoding (schema dict)",
                            extra={
                                "model": target_model,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
                    else:
                        # OpenAI shorthand {"type": "json_object"} or constrained_decoding=False
                        completion_kwargs["response_format"] = response_format
                        logger.debug(
                            "Using JSON schema for structured output",
                            extra={
                                "model": target_model,
                                "response_format": response_format,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
            except ImportError:
                logger.warning(
                    "Pydantic not available, response_format ignored",
                    extra={"model": target_model}
                )
        
        # Explicitly disable streaming for non-streaming calls
        completion_kwargs["stream"] = False

        logger.info(
            "Dispatching async completion",
            extra={
                "llm_provider": "litellm",
                "model": target_model,
                "temperature": completion_kwargs.get("temperature"),
                "max_tokens": completion_kwargs.get("max_tokens"),
                "stream": completion_kwargs.get("stream"),
                "request_id": request_id,
                "trace_id": trace_id,
            },
        )

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1.0
        
        # Get circuit breaker for this provider
        circuit_breaker = None
        provider_name = None
        if self._enable_circuit_breaker and self._circuit_breaker_registry:
            provider_name = self._extract_provider_from_model(target_model)
            circuit_breaker = await self._circuit_breaker_registry.get_breaker(provider_name)
        
        for attempt in range(max_retries + 1):
            try:
                # Track LLM call timing
                llm_start = time.time()
                
                # Define the LLM call as an async function for circuit breaker wrapping
                async def make_llm_call():
                    # When api_base is set (vLLM / Ollama), LiteLLM constructs
                    # its own AsyncOpenAI client internally and would try to
                    # read .api_key from any client we pass — which fails for
                    # httpx.AsyncClient.  Only pass our pooled client when
                    # using a cloud provider with no custom base URL.
                    http_client = None if self._api_base else self._http_client
                    return await litellm.acompletion(
                        model=target_model,
                        messages=messages_list,
                        api_key=self._api_key,
                        api_base=self._api_base,
                        client=http_client,
                        **completion_kwargs,
                    )
                
                # Execute with circuit breaker protection if enabled
                if circuit_breaker:
                    try:
                        response = await circuit_breaker.call(make_llm_call)
                    except CircuitBreakerOpen as cb_error:
                        # Circuit breaker is open - fail fast
                        logger.error(
                            "Circuit breaker OPEN for provider %s",
                            provider_name,
                            extra={
                                "provider": provider_name,
                                "model": target_model,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
                        raise RuntimeError(
                            f"LLM provider '{provider_name}' is temporarily unavailable. {str(cb_error)}"
                        ) from cb_error
                else:
                    # No circuit breaker - direct call
                    response = await make_llm_call()
                
                llm_duration = (time.time() - llm_start) * 1000  # Convert to milliseconds

                # Convert ModelResponse to dict if needed (litellm sometimes returns ModelResponse objects)
                if hasattr(response, 'model_dump'):
                    response = response.model_dump()
                elif hasattr(response, 'dict'):
                    response = response.dict()
                elif not isinstance(response, dict):
                    raise TypeError(
                        f"Expected dict response from litellm.acompletion, got {type(response).__name__}. "
                        f"Stream setting was: {completion_kwargs.get('stream')}"
                    )

                # Check if LiteLLM parsed the response (structured outputs)
                message_obj = response["choices"][0]["message"]
                if hasattr(message_obj, "parsed") and message_obj.parsed is not None:
                    # Structured output was parsed by LiteLLM (native providers)
                    message = message_obj.parsed
                    logger.info(
                        "Received structured output (parsed by LiteLLM)",
                        extra={
                            "model": target_model,
                            "parsed_type": type(message).__name__,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        }
                    )
                elif _constrained_parse_model is not None:
                    # vLLM constrained decoding: parse JSON string into Pydantic model
                    raw_content = (
                        message_obj.get("content", "")
                        if isinstance(message_obj, dict)
                        else getattr(message_obj, "content", "")
                    )
                    try:
                        message = _constrained_parse_model.model_validate_json(raw_content)
                        logger.info(
                            "Received structured output (parsed from vLLM guided_json)",
                            extra={
                                "model": target_model,
                                "parsed_type": _constrained_parse_model.__name__,
                                "request_id": request_id,
                                "trace_id": trace_id,
                            }
                        )
                    except Exception:
                        logger.warning(
                            "Failed to parse vLLM guided_json response as %s, returning raw string",
                            _constrained_parse_model.__name__,
                            extra={"model": target_model, "request_id": request_id},
                        )
                        message = raw_content
                else:
                    # Standard text response
                    message = (
                        message_obj.get("content", "")
                        if isinstance(message_obj, dict)
                        else getattr(message_obj, "content", "")
                    )
                
                usage = response.get("usage", {})
                total_tokens = usage.get("total_tokens") if usage else None
                
                # Parse rate limit headers if available
                response_headers = getattr(response, "_hidden_params", {}).get("response_headers", {})
                rate_limit_info = self._parse_rate_limit_headers(response_headers)

                metadata = {
                    "provider": "litellm",
                    "model": target_model,
                    "usage": usage,
                    "response_id": response.get("id"),
                    "prompt_tokens": usage.get("prompt_tokens") if usage else None,
                    "completion_tokens": usage.get("completion_tokens") if usage else None,
                    "llm_duration_ms": round(llm_duration, 2),
                    "request_id": request_id,
                    "trace_id": trace_id,
                }
                
                if rate_limit_info:
                    metadata["rate_limit_info"] = rate_limit_info
                
                logger.info(
                    "LLM completion successful",
                    extra={
                        "llm_duration_ms": round(llm_duration, 2),
                        "total_tokens": total_tokens,
                        "model": target_model,
                        "request_id": request_id,
                        "trace_id": trace_id,
                    }
                )

                logger.info(
                    "Completion received",
                    extra={
                        "llm_provider": "litellm",
                        "model": target_model,
                        "total_tokens": total_tokens,
                        "attempt": attempt + 1,
                        "request_id": request_id,
                        "trace_id": trace_id,
                    },
                )

                return LLMCompletionResult(
                    context=message,
                    model=target_model,
                    total_tokens=total_tokens,
                    metadata=metadata,
                )
                
            except CircuitBreakerOpen:
                # Circuit breaker is open - don't retry, fail immediately
                raise
            except Exception as e:
                # Check if this is a rate limit error
                is_rate_limit_error = self._is_rate_limit_error(e)
                
                # Rate limit errors should NOT trigger circuit breaker
                # (they're temporary throttling, not service outages)
                # The circuit breaker in the try block already handles provider failures
                
                if is_rate_limit_error and attempt < max_retries:
                    # Extract retry_after from error or use exponential backoff
                    retry_after = self._extract_retry_after(e)
                    if retry_after is None:
                        retry_after = base_delay * (2 ** attempt)
                    
                    logger.warning(
                        "Rate limit hit, retrying after %s seconds (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        max_retries,
                        exc_info=False,
                    )
                    
                    # Use async sleep instead of blocking time.sleep
                    await asyncio.sleep(retry_after)
                    continue
                
                # For rate limit errors on final attempt, raise RateLimitExceeded
                if is_rate_limit_error:
                    retry_after = self._extract_retry_after(e) or 60.0
                    raise RateLimitExceeded(
                        message=f"Rate limit exceeded for model {target_model}: {str(e)}",
                        retry_after=int(retry_after) if retry_after else None,
                        limit_type="provider",
                        scope="global",
                    )
                
                # Non-rate-limit errors are raised immediately
                raise
        
        # This line should never be reached (loop always returns or raises)
        raise RuntimeError("Unexpected: complete_async loop terminated without return or exception")

    def complete(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Union[Dict[str, Any], Type["BaseModel"]]] = None,
        **kwargs: Any,
    ) -> LLMCompletionResult:
        """Complete a prompt with automatic retry on rate limit errors (synchronous wrapper)."""
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        target_model = model or self._default_model
        if not target_model:
            raise ValueError("Model must be supplied either at initialization or call time")

        # Build messages array
        if messages:
            # Use provided conversation history
            messages_list = messages.copy()
        else:
            # Build from prompts
            messages_list = []
            if system_prompt:
                messages_list.append({"role": "system", "content": system_prompt})
            if user_prompt:
                messages_list.append({"role": "user", "content": user_prompt})

        completion_kwargs: Dict[str, Any] = {**self._default_completion_kwargs, **kwargs}
        completion_kwargs.setdefault("temperature", temperature)
        if max_tokens is not None and "max_tokens" not in completion_kwargs:
            completion_kwargs["max_tokens"] = max_tokens
        
        # Get current request context for distributed tracing (needed for logging below)
        request_id = get_request_id()
        trace_id = get_trace_id()
        
        # Handle response_format for structured outputs
        # Supports both Pydantic models (for providers with native structured output support)
        # and JSON schema dicts (for broader compatibility)
        if response_format is not None:
            try:
                from pydantic import BaseModel
                if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                    # Use Pydantic model directly - litellm will convert to appropriate format
                    # Works with: OpenAI (gpt-4o+), Anthropic (Claude 3.5+), Google (Gemini 1.5+)
                    completion_kwargs["response_format"] = response_format
                    logger.debug(
                        "Using Pydantic model for structured output",
                        extra={
                            "model": target_model,
                            "response_format_type": response_format.__name__,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        }
                    )
                elif isinstance(response_format, dict):
                    # Use JSON schema dict (e.g., {"type": "json_object"})
                    completion_kwargs["response_format"] = response_format
                    logger.debug(
                        "Using JSON schema for structured output",
                        extra={
                            "model": target_model,
                            "response_format": response_format,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        }
                    )
            except ImportError:
                logger.warning(
                    "Pydantic not available, response_format ignored",
                    extra={"model": target_model}
                )
        
        # Explicitly disable streaming for non-streaming calls
        completion_kwargs["stream"] = False

        logger.info(
            "Dispatching completion",
            extra={
                "llm_provider": "litellm",
                "model": target_model,
                "temperature": completion_kwargs.get("temperature"),
                "max_tokens": completion_kwargs.get("max_tokens"),
                "request_id": request_id,
                "trace_id": trace_id,
            },
        )

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                response = litellm.completion(
                    model=target_model,
                    messages=messages_list,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    **completion_kwargs,
                )

                # Convert ModelResponse to dict if needed (litellm sometimes returns ModelResponse objects)
                if hasattr(response, 'model_dump'):
                    response = response.model_dump()
                elif hasattr(response, 'dict'):
                    response = response.dict()
                elif not isinstance(response, dict):
                    raise TypeError(
                        f"Expected dict response from litellm.completion, got {type(response).__name__}. "
                        f"Stream setting was: {completion_kwargs.get('stream')}"
                    )

                # Check if LiteLLM parsed the response (structured outputs)
                message_obj = response["choices"][0]["message"]
                if hasattr(message_obj, "parsed") and message_obj.parsed is not None:
                    # Structured output was parsed by LiteLLM
                    message = message_obj.parsed
                    logger.info(
                        "Received structured output (parsed by LiteLLM)",
                        extra={
                            "model": target_model,
                            "parsed_type": type(message).__name__,
                            "request_id": request_id,
                            "trace_id": trace_id,
                        }
                    )
                else:
                    # Standard text response
                    message = message_obj.get("content", "")
                
                usage = response.get("usage", {})
                total_tokens = usage.get("total_tokens") if usage else None
                
                # Parse rate limit headers if available
                response_headers = getattr(response, "_hidden_params", {}).get("response_headers", {})
                rate_limit_info = self._parse_rate_limit_headers(response_headers)

                metadata = {
                    "provider": "litellm",
                    "model": target_model,
                    "usage": usage,
                    "response_id": response.get("id"),
                    "prompt_tokens": usage.get("prompt_tokens") if usage else None,
                    "completion_tokens": usage.get("completion_tokens") if usage else None,
                    "request_id": request_id,
                    "trace_id": trace_id,
                }
                
                if rate_limit_info:
                    metadata["rate_limit_info"] = rate_limit_info

                logger.info(
                    "Completion received",
                    extra={
                        "llm_provider": "litellm",
                        "model": target_model,
                        "total_tokens": total_tokens,
                        "attempt": attempt + 1,
                        "request_id": request_id,
                        "trace_id": trace_id,
                    },
                )

                return LLMCompletionResult(
                    context=message,
                    model=target_model,
                    total_tokens=total_tokens,
                    metadata=metadata,
                )
                
            except Exception as e:
                # Check if this is a rate limit error
                is_rate_limit_error = self._is_rate_limit_error(e)
                
                if is_rate_limit_error and attempt < max_retries:
                    # Extract retry_after from error or use exponential backoff
                    retry_after = self._extract_retry_after(e)
                    if retry_after is None:
                        retry_after = base_delay * (2 ** attempt)
                    
                    logger.warning(
                        "Rate limit hit, retrying after %s seconds (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        max_retries,
                        exc_info=False,
                    )
                    
                    # Sync method: use time.sleep directly (no event loop required)
                    time.sleep(retry_after)
                    continue
                
                # For rate limit errors on final attempt, raise RateLimitExceeded
                if is_rate_limit_error:
                    retry_after = self._extract_retry_after(e) or 60.0
                    raise RateLimitExceeded(
                        message=f"Rate limit exceeded for model {target_model}: {str(e)}",
                        retry_after=int(retry_after) if retry_after else None,
                        limit_type="provider",
                        scope="global",
                    )
                
                # Non-rate-limit errors are raised immediately
                raise
        
        # This line should never be reached (loop always returns or raises)
        raise RuntimeError("Unexpected: complete loop terminated without return or exception")

    def get_model_info(self, model: str) -> Dict[str, Any]:
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        info: Dict[str, Any] = {"model": model, "provider": "litellm"}

        if hasattr(litellm, "get_model_cost"):
            try:  # pragma: no cover - optional helper for supported metadata
                cost = litellm.get_model_cost(model=model)
                if cost:
                    info["pricing"] = cost
            except Exception:
                pass

        return info
    
    def get_rate_limits(
        self,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> "RateLimitConfig":
        """
        Get rate limits for the provider/model.
        
        Returns provider-specific rate limits based on the model prefix.
        Falls back to conservative defaults for unknown providers.
        """
        target_model = model or self._default_model
        target_api_base = self._api_base if api_base is None else api_base
        defaults = get_model_defaults(target_model, api_base=target_api_base)
        if defaults.rate_limit is not None:
            return defaults.rate_limit
        return RateLimitConfig(
            requests_per_minute=60,
            tokens_per_minute=10000,
            max_concurrent_requests=5,
        )
    
    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception is a rate limit error."""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Check for common rate limit indicators
        rate_limit_indicators = [
            "rate limit",
            "ratelimit",
            "429",
            "quota exceeded",
            "too many requests",
            "503",  # Service unavailable (often temporary)
        ]
        
        return any(indicator in error_str or indicator in error_type for indicator in rate_limit_indicators)
    
    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry_after duration from error message or headers."""
        error_str = str(error)
        
        # Try to find "retry after X seconds" pattern
        patterns = [
            r"retry after ([0-9.]+) seconds?",
            r"retry_after[:\s]+([0-9.]+)",
            r"wait ([0-9.]+) seconds?",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass
        
        return None
    
    def _parse_rate_limit_headers(self, headers: Dict[str, Any]) -> Dict[str, Any]:
        """Parse rate limit information from response headers."""
        if not headers:
            return {}
        
        rate_limit_info = {}
        
        # Normalize header keys to lowercase for case-insensitive lookup
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        
        # Common rate limit headers
        if "x-ratelimit-remaining" in normalized_headers:
            try:
                rate_limit_info["requests_remaining"] = int(normalized_headers["x-ratelimit-remaining"])
            except (ValueError, TypeError):
                pass
        
        if "x-ratelimit-limit" in normalized_headers:
            try:
                rate_limit_info["requests_limit"] = int(normalized_headers["x-ratelimit-limit"])
            except (ValueError, TypeError):
                pass
        
        if "x-ratelimit-reset" in normalized_headers:
            # Reset time can be Unix timestamp or duration
            try:
                rate_limit_info["reset_time"] = float(normalized_headers["x-ratelimit-reset"])
            except (ValueError, TypeError):
                pass
        
        if "retry-after" in normalized_headers:
            try:
                rate_limit_info["retry_after"] = float(normalized_headers["retry-after"])
            except (ValueError, TypeError):
                pass
        
        return rate_limit_info
    
    def get_circuit_breaker_metrics(self) -> Dict[str, Any]:
        """
        Get metrics for all circuit breakers.
        
        Returns:
            Dict mapping provider name to circuit breaker metrics
        """
        if not self._enable_circuit_breaker or not self._circuit_breaker_registry:
            return {"circuit_breaker_enabled": False}
        
        return {
            "circuit_breaker_enabled": True,
            "providers": self._circuit_breaker_registry.get_all_metrics()
        }
