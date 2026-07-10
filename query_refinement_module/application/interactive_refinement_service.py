"""Shared interactive workflow for CLI- and UI-driven refinement sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from query_refinement_module.core import UserCommand, is_user_command, parse_user_command


@dataclass(slots=True)
class InteractivePrompt:
    """Presentation-ready prompt payload for an interactive refinement step."""

    aspect_id: str
    aspect_name: str
    aspect_description: str
    question: str
    examples: List[str] = field(default_factory=list)
    dependency_context: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class InteractiveTurnResult:
    """Result of one interactive user turn."""

    message: Optional[str] = None
    prompt: Optional[InteractivePrompt] = None
    synthesis_requested: bool = False
    command_type: Optional[str] = None
    command_payload: Optional[Dict[str, Any]] = None


class InteractiveRefinementService:
    """Reusable interactive workflow adapter for CLI and future Chainlit UI."""

    def __init__(self, manager) -> None:
        self._manager = manager

    def start_session(self, *, original_query: str, refinement_framework):
        """Create a sequential session for interactive refinement."""
        return self._manager.initialize_sequential(original_query, refinement_framework)

    async def get_next_prompt(self, session) -> Optional[InteractivePrompt]:
        """Resolve the next user-visible prompt, auto-advancing clear aspects."""
        while not session.synthesis_requested:
            step = session.get_next_unrefined_aspect()
            if not step:
                return None

            if self._get_step_question(step):
                return self._build_prompt(session=session, step=step)

            mode = "followup" if self._get_conversation_history(step) else "initial"
            result = await self._manager.get_analysis_prompts(
                session=session,
                aspect_id=step.refinement_aspect.id,
                mode=mode,
            )
            status = self._manager.process_analysis_result(
                session=session,
                aspect_id=step.refinement_aspect.id,
                result=result,
            )
            if status.get("complete"):
                continue

            return self._build_prompt(session=session, step=step, fallback_examples=result.examples or [])

        return None

    async def submit_input(
        self,
        *,
        session,
        user_input: str,
        selected_example: bool = False,
    ) -> InteractiveTurnResult:
        """Apply one answer or command to the interactive session."""
        if is_user_command(user_input):
            cmd_result = parse_user_command(user_input)
            payload = session.handle_command(cmd_result)
            prompt = None

            if payload.get("regenerate_question"):
                prompt = await self.get_next_prompt(session)
            elif cmd_result.command not in {UserCommand.HELP, UserCommand.STATUS, UserCommand.STEPS}:
                prompt = await self.get_next_prompt(session)

            return InteractiveTurnResult(
                message=payload.get("message"),
                prompt=prompt,
                synthesis_requested=session.synthesis_requested,
                command_type=cmd_result.command.value if cmd_result.is_valid else None,
                command_payload=payload,
            )

        step = session.get_active_step()
        if not step:
            return InteractiveTurnResult(
                message="No active refinement step.",
                synthesis_requested=session.synthesis_requested,
            )

        question = self._get_step_question(step) or f"Please provide details about {step.refinement_aspect.name}"
        step.add_follow_up(question=question, response=user_input)

        if selected_example:
            step.is_complete = True
            return InteractiveTurnResult(
                prompt=await self.get_next_prompt(session),
                synthesis_requested=session.synthesis_requested,
            )

        followup_result = await self._manager.run_followup_until_clear(
            session,
            aspect_id=step.refinement_aspect.id,
            max_rounds=5,
        )

        if followup_result.get("is_complete", False):
            step.is_complete = True
            return InteractiveTurnResult(
                prompt=await self.get_next_prompt(session),
                synthesis_requested=session.synthesis_requested,
            )

        return InteractiveTurnResult(
            prompt=self._build_prompt(session=session, step=step),
            synthesis_requested=session.synthesis_requested,
        )

    async def synthesize(self, session) -> Dict[str, Any]:
        """Run the chained synthesis flow for the interactive session."""
        return await self._manager.synthesize_refined_query(session)

    def _build_prompt(self, *, session, step, fallback_examples: Optional[List[str]] = None) -> InteractivePrompt:
        examples = list(getattr(step, "quick_replies", None) or fallback_examples or [])
        return InteractivePrompt(
            aspect_id=step.refinement_aspect.id,
            aspect_name=step.refinement_aspect.name,
            aspect_description=step.refinement_aspect.description or "",
            question=self._get_step_question(step) or f"Please provide details about {step.refinement_aspect.name}",
            examples=examples,
            dependency_context=session.get_dependency_context(step.refinement_aspect.id),
        )

    def _get_step_question(self, step) -> Optional[str]:
        return (
            getattr(step, "follow_up_question", None)
            or getattr(step, "refinement_question", None)
            or getattr(step, "analysis_suggested_question", None)
        )

    def _get_conversation_history(self, step) -> List[Dict[str, Any]]:
        return list(
            getattr(step, "conversation_history", None)
            or getattr(step, "follow_up_history", None)
            or []
        )