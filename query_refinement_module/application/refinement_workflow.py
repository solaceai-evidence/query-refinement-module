"""Shared application-layer workflow helpers for refinement sessions."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.db.crud import (
    update_refinement_step_final_value,
    update_refinement_step_generated_examples,
    update_refinement_step_generated_question,
)
from query_refinement_module.next_prompt import build_fallback_question, resolve_next_prompt


logger = logging.getLogger(__name__)


async def generate_question_with_retry(
    manager: QueryRefinementManager,
    session,
    aspect_id: str,
    mode: str = "initial",
    max_retries: int = 1,
):
    """Generate a question with one retry layer around the LLM call."""
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = 2 ** attempt
                logger.info(
                    "Retry attempt %d/%d after %ss delay for aspect %s",
                    attempt,
                    max_retries,
                    delay,
                    aspect_id,
                )
                await asyncio.sleep(delay)

            return await manager.get_analysis_prompts(
                session=session,
                aspect_id=aspect_id,
                mode=mode,
            )
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc
            logger.warning(
                "LLM call failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if attempt >= max_retries:
                raise

    raise last_error if last_error else RuntimeError("Question generation failed")


def deserialize_refinement_value(value: Optional[str]) -> Optional[Any]:
    """Deserialize persisted final_value into a native python value when possible."""
    if value is None or not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    if stripped[0] in ["{", "["]:
        try:
            return json.loads(stripped)
        except Exception:
            return value

    return value


def db_step_matches_aspect(db_step: Any, aspect: Any) -> bool:
    """Match persisted step rows to framework aspects, preferring stable IDs."""
    persisted_aspect_id = getattr(db_step, "aspect_id", None)
    if persisted_aspect_id:
        return persisted_aspect_id == aspect.id
    return getattr(db_step, "aspect_name", None) == aspect.name


def find_db_step_for_aspect(db_steps: List[Any], aspect: Any) -> Optional[Any]:
    """Locate the DB row corresponding to a framework aspect."""
    return next((step for step in db_steps if db_step_matches_aspect(step, aspect)), None)


def restore_session_from_db_state(session, db_steps: List[Any]) -> None:
    """Restore in-memory session state from persisted DB refinement step rows."""
    for db_step in db_steps:
        session_step = next(
            (step for step in session.steps if db_step_matches_aspect(db_step, step.refinement_aspect)),
            None,
        )
        if not session_step:
            continue

        for followup in db_step.followup_history:
            session_step.conversation_history.append(
                {
                    "question": followup.question,
                    "response": followup.answer or "",
                }
            )

        if db_step.generated_question:
            session_step.follow_up_question = db_step.generated_question
        elif session_step.conversation_history:
            last_followup = db_step.followup_history[-1]
            session_step.follow_up_question = last_followup.question

        generated_examples = getattr(db_step, "generated_examples", None)
        if generated_examples:
            session_step.quick_replies = list(generated_examples)

        has_final_value = db_step.final_value is not None and str(db_step.final_value).strip() != ""
        if has_final_value:
            session_step.normalized_value = deserialize_refinement_value(db_step.final_value)

        session_step.was_skipped = bool(db_step.was_skipped)
        session_step.is_complete = bool(
            db_step.is_complete
            or db_step.was_skipped
            or db_step.user_ended_early
            or has_final_value
        )

        if session_step.was_skipped and not has_final_value:
            session_step.normalized_value = None


async def build_next_prompt(
    manager: QueryRefinementManager,
    session,
    *,
    db=None,
    db_steps: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build the next prompt from the next unresolved refinement aspect."""

    def _build_prompt_payload(_, step, question: str) -> Dict[str, Any]:
        return {
            "aspect_id": step.refinement_aspect.id,
            "name": step.refinement_aspect.name,
            "aspect_name": step.refinement_aspect.name,
            "question": question,
            "description": step.refinement_aspect.description or "",
            "examples": getattr(step, "quick_replies", []),
        }

    def _persist_auto_completion(step, status: Dict[str, Any]) -> None:
        logger.info(
            "  -> Dimension '%s' auto-completed with value: %s",
            step.refinement_aspect.name,
            str(status.get("current", ""))[:100],
        )
        if not db or not db_steps or step.normalized_value_as_str is None:
            return

        db_step_row = find_db_step_for_aspect(db_steps, step.refinement_aspect)
        if not db_step_row:
            return

        try:
            update_refinement_step_final_value(
                db,
                db_step_row.id,
                step.normalized_value_as_str,
                is_complete=True,
                was_skipped=False,
                user_ended_early=False,
            )
        except Exception as exc:  # pragma: no cover - persistence warning path
            logger.warning(
                "  -> Could not persist auto-completion for '%s': %s",
                step.refinement_aspect.name,
                exc,
            )

    async def _analyze_initial(step):
        llm_start = time.time()
        logger.info("  -> Generating question via LLM analysis for aspect '%s'", step.refinement_aspect.name)
        logger.info("  -> Aspect ID: %s, mode: initial", step.refinement_aspect.id)

        analysis_result = await generate_question_with_retry(
            manager=manager,
            session=session,
            aspect_id=step.refinement_aspect.id,
            mode="initial",
        )

        llm_duration = (time.time() - llm_start) * 1000
        logger.info(
            "  -> LLM call completed in %.2fms for aspect '%s'",
            llm_duration,
            step.refinement_aspect.name,
        )
        return analysis_result

    next_prompt = await resolve_next_prompt(
        session,
        analyze_initial=_analyze_initial,
        process_analysis_result=lambda step, result: manager.process_analysis_result(
            session=session,
            aspect_id=step.refinement_aspect.id,
            result=result,
        ),
        build_payload=_build_prompt_payload,
        on_auto_completed=_persist_auto_completion,
        logger=logger,
        failure_log_message="  -> LLM analysis failed for aspect '%s': %s",
        fallback_question_builder=build_fallback_question,
    )

    if next_prompt:
        logger.info(
            "  -> Prepared question for '%s': '%s...'",
            next_prompt["name"],
            next_prompt["question"][:100],
        )
        return next_prompt

    logger.info("  -> No unrefined aspects remaining, returning None")
    return None


def persist_generated_question(
    db,
    db_steps: List[Any],
    next_prompt: Optional[Dict[str, Any]],
) -> None:
    """Persist a generated question and examples so they survive restarts."""
    if not next_prompt or not db:
        return

    aspect_id = next_prompt.get("aspect_id")
    aspect_name = next_prompt.get("name")
    question = next_prompt.get("question")
    if (not aspect_id and not aspect_name) or not question:
        return

    db_step = next(
        (
            step for step in db_steps
            if (aspect_id and getattr(step, "aspect_id", None) == aspect_id)
            or (not getattr(step, "aspect_id", None) and aspect_name and getattr(step, "aspect_name", None) == aspect_name)
        ),
        None,
    )
    if not db_step:
        return

    try:
        update_refinement_step_generated_question(db, db_step.id, question)
    except Exception as exc:  # pragma: no cover - persistence warning path
        logger.warning("Could not persist generated_question for '%s': %s", aspect_id or aspect_name, exc)

    examples = next_prompt.get("examples") or []
    if examples:
        try:
            update_refinement_step_generated_examples(db, db_step.id, examples)
        except Exception as exc:  # pragma: no cover - persistence warning path
            logger.warning("Could not persist generated_examples for '%s': %s", aspect_id or aspect_name, exc)


def get_active_prompt(session) -> Optional[Dict[str, Any]]:
    """Return the currently active question if it already exists in session state."""
    active_step = session.get_active_step()
    if not active_step or not active_step.follow_up_question:
        return None

    return {
        "aspect_id": active_step.refinement_aspect.id,
        "name": active_step.refinement_aspect.name,
        "aspect_name": active_step.refinement_aspect.name,
        "question": active_step.follow_up_question,
        "description": active_step.refinement_aspect.description or "",
        "examples": getattr(active_step, "quick_replies", []),
    }


def is_session_ready_for_synthesis(session) -> bool:
    """Return True when synthesis can be safely executed for a session."""
    if not session:
        return False
    return bool(session.synthesis_requested or session.is_complete())


def build_status_payload(query_id: int, db_query, session, summary: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the current workflow state for status-like responses."""
    active_step = session.get_active_step()
    aspects = [
        {
            "aspect_id": step.refinement_aspect.id,
            "name": step.refinement_aspect.name,
            "is_complete": step.is_complete,
            "needs_review": step.needs_review,
            "was_skipped": step.was_skipped,
            "status": (
                "completed" if step.is_complete and not step.needs_review else
                "needs review" if step.needs_review else
                "active" if step == active_step else
                "not started"
            ),
        }
        for step in session.steps
    ]

    conversation_history = [{
        "type": "query",
        "content": db_query.original_query,
    }]
    for step in session.steps:
        for qa in step.conversation_history:
            conversation_history.append(
                {
                    "type": "question",
                    "content": qa.get("question", ""),
                    "aspectId": step.refinement_aspect.id,
                    "aspectName": step.refinement_aspect.name,
                }
            )
            if qa.get("response"):
                conversation_history.append(
                    {
                        "type": "answer",
                        "content": qa["response"],
                        "aspectId": step.refinement_aspect.id,
                    }
                )

    next_prompt = None if session.synthesis_requested else get_active_prompt(session)
    ready_for_synthesis = is_session_ready_for_synthesis(session)

    return {
        "query_id": query_id,
        "original_query": db_query.original_query,
        "refined_query": db_query.refined_query,
        "is_complete": session.is_complete(),
        "current_aspect": active_step.refinement_aspect.name if active_step else None,
        "aspects_summary": summary,
        "next_prompt": next_prompt,
        "ready_for_synthesis": ready_for_synthesis,
        "aspects": aspects,
        "conversation_history": conversation_history,
    }
