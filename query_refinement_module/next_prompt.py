"""Shared next-prompt resolution helpers for refinement workflows."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar


PromptT = TypeVar("PromptT")
AnalysisResultT = TypeVar("AnalysisResultT")


def get_next_step(session: Any):
    """Return the next step requiring user attention, preferring dependency order."""

    get_next_unrefined_aspect = getattr(session, "get_next_unrefined_aspect", None)
    if callable(get_next_unrefined_aspect):
        return get_next_unrefined_aspect()
    return session.get_active_step()


def build_fallback_question(step: Any) -> str:
    """Return the generic fallback question for a refinement step."""

    return f"Please provide details about {step.refinement_aspect.name}"


async def resolve_next_prompt(
    session: Any,
    *,
    analyze_initial: Callable[[Any], Awaitable[AnalysisResultT]],
    process_analysis_result: Callable[[Any, AnalysisResultT], dict[str, Any]],
    build_payload: Callable[[Any, Any, str], PromptT],
    on_auto_completed: Optional[Callable[[Any, dict[str, Any]], None]] = None,
    logger: Optional[logging.Logger] = None,
    failure_log_message: str = "Failed to analyze next prompt for aspect '%s': %s",
    fallback_question_builder: Callable[[Any], str] = build_fallback_question,
) -> Optional[PromptT]:
    """Resolve the next prompt from the next unfinished refinement step.

    The shared flow is:
    - choose the next unresolved step in dependency order when possible
    - reuse an existing follow-up question when already available
    - run initial analysis when no question exists yet
    - skip auto-completed steps and continue to the next candidate
    - fall back to a generic question if analysis fails
    """

    max_attempts = max(len(getattr(session, "steps", []) or []), 1)
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        step = get_next_step(session)
        if not step:
            return None

        if step.follow_up_question:
            return build_payload(session, step, step.follow_up_question)

        try:
            analysis_result = await analyze_initial(step)
            status = process_analysis_result(step, analysis_result)
        except Exception as exc:  # pragma: no cover - caller-specific failure paths
            if logger:
                logger.warning(
                    failure_log_message,
                    step.refinement_aspect.name,
                    exc,
                )
            fallback_question = fallback_question_builder(step)
            step.follow_up_question = fallback_question
            return build_payload(session, step, fallback_question)

        if status.get("complete", False):
            if on_auto_completed:
                on_auto_completed(step, status)
            continue

        question = status.get("next_question") or step.follow_up_question
        if not question:
            fallback_question = fallback_question_builder(step)
            step.follow_up_question = fallback_question
            question = fallback_question

        return build_payload(session, step, question)

    return None