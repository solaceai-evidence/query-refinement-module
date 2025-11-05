"""
Query refinement chatbot

This module provides interactive chatbot functionality to refine user queries.
It guides users through a series of questions to better understand their needs
and improve the accuracy of responses.

Architecture:
The module is organized into several layers:

1. **Schemas** (schemas.py):
    - Defines pre-built refinement schemas
    - Dimension definitions with prompts and validation

2. **Interfaces** (interfaces.py):
    - Abstract base classes for refinement strategies
    - Contracts for implementing LLM providers and tracers
    - Type definitions and protocols

3. **Providers** (providers.py):
    - Implementation of tracing providers, emitters, session storage, and LLM adapters

4. **Core Refinement Logic** (core.py):
    - Main classes and functions for query refinement (QueryRefinementManager)
    - Orchestration of the refinement process
    - Session state management and command handling utilities

5. **Service Layer** (service.py, api_models.py):
    - Async-friendly service facade for integrations
    - Typed request/response models for API exposure
    - Session persistence via the storage interface
"""

__version__ = "0.1.0"

from .cli import build_manager as build_cli_manager, main as cli_main, run_cli
from .core import QueryRefinementManager, QueryRefinementSession
from .providers import InMemorySessionStorage, LiteLLMProvider, RedisSessionStorage
from .service import QueryRefinementService, build_manager_from_env
from .analyzers import LLMQueryAnalyzer
from .settings import LLMSettings
from .api_models import (
    SessionCreateRequest,
    SessionCreateResponse,
    InteractionRequest,
    InteractionResponse,
    SessionStatusResponse,
    NextPrompt,
)

__all__ = [
    "QueryRefinementManager",
    "QueryRefinementSession",
    "QueryRefinementService",
    "InMemorySessionStorage",
    "RedisSessionStorage",
    "LiteLLMProvider",
    "LLMQueryAnalyzer",
    "cli_main",
    "run_cli",
    "build_cli_manager",
    "build_manager_from_env",
    "LLMSettings",
    "SessionCreateRequest",
    "SessionCreateResponse",
    "InteractionRequest",
    "InteractionResponse",
    "SessionStatusResponse",
    "NextPrompt",
]