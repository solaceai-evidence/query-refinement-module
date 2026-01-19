"""Typed request and response models for the query-refinement service layer."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .schema import RefinementAspect


@dataclass
class NextPrompt:
    """Represents the next question that should be shown to the user."""

    aspect_id: str
    aspect_name: str
    question: str
    reasoning: Optional[str] = None
    dependency_context: Dict[str, str] = field(default_factory=dict)


@dataclass
class SessionCreateRequest:
    """Input payload for creating a new refinement session."""

    original_query: str
    refinement_framework: List[RefinementAspect]
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SessionCreateResponse:
    """Returned after successfully creating a refinement session."""

    session_id: str
    summary: Dict[str, Any]
    next_prompt: Optional[NextPrompt]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionRequest:
    """User turn payload (command or natural-language response)."""

    session_id: str
    message: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class InteractionResponse:
    """Result of processing a user turn."""

    session_id: str
    success: bool
    message: str
    next_prompt: Optional[NextPrompt]
    summary: Dict[str, Any]
    invalidated_aspects: List[str] = field(default_factory=list)
    session_complete: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionStatusResponse:
    """Snapshot of the current refinement session status."""

    session_id: str
    summary: Dict[str, Any]
    next_prompt: Optional[NextPrompt]
    session_complete: bool
    history: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
