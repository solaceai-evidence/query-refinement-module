"""Public package surface for the query refinement prototype."""

__version__ = "2.0.0"

from .core import QueryRefinementManager
from .session_models import AspectRefinementState, RefinementSession
from .providers import (
    FileTracingProvider,
    InMemorySessionStorage,
    LiteLLMProvider,
    RedisSessionStorage,
)
from .settings import LLMSettings
from .logging_utils import configure_file_logging

__all__ = [
    "QueryRefinementManager",
    "RefinementSession",
    "InMemorySessionStorage",
    "RedisSessionStorage",
    "LiteLLMProvider",
    "FileTracingProvider",
    "configure_file_logging",
    "cli_main",
    "run_cli",
    "build_cli_manager",
    "LLMSettings",
]