__version__ = "0.1.0"

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
    - Implementation of LLM providers (OpenAI, Anthropic, etc.)
    - LangSmith tracing integration

4. **Core Refinement Logic** (refinement_logic.py):
    - Main classes and functions for query refinement (QueryRefinementManager)
    - Orchestration of the refinement process
    - Session state management

5. **API Layer** (api.py, models.py):
    - FastAPI endpoints for interacting with the refinement chatbot
    - Pydantic models for request and response validation
    - Session persistence
"""