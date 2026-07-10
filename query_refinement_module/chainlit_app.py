"""Chainlit entry point for the shared interactive refinement workflow."""

from __future__ import annotations

from typing import Any, Optional

from query_refinement_module.api.dependencies import get_refinement_manager
from query_refinement_module.application import InteractivePrompt, InteractiveRefinementService
from query_refinement_module.application.interactive_refinement_helpers import (
    build_search_expansion_input_from_synthesis,
    resolve_numeric_examples,
)
from query_refinement_module.schema import registry

try:
    import chainlit as cl
except ImportError:  # pragma: no cover - import-safe for environments without Chainlit
    cl = None


class ChainlitWorkflowState:
    def __init__(self) -> None:
        self.framework_name: Optional[str] = None
        self.original_query: Optional[str] = None
        self.session: Any = None
        self.prompt: Optional[InteractivePrompt] = None


def _get_interactive_service() -> InteractiveRefinementService:
    return InteractiveRefinementService(get_refinement_manager())


def _framework_names() -> list[str]:
    names = registry.list_frameworks()
    return sorted(names)


def _framework_help_text() -> str:
    names = _framework_names()
    if not names:
        return "No refinement frameworks are available. Check REFINEMENT_FRAMEWORK_PATH and restart the app."
    joined = "\n".join(f"- {name}" for name in names)
    return (
        "## Query Refinement Chat\n\n"
        "Choose a refinement framework by sending its name.\n\n"
        f"Available frameworks:\n{joined}\n\n"
        "After that, send your research question to begin the guided refinement dialogue."
    )


def _format_prompt(prompt: InteractivePrompt) -> str:
    lines = [f"## {prompt.aspect_name}"]
    if prompt.aspect_description:
        lines.append(prompt.aspect_description)
    if prompt.dependency_context:
        lines.append("")
        lines.append("Context already captured:")
        for item in prompt.dependency_context.values():
            lines.append(f"- {item['name']}: {item['value']}")
    lines.append("")
    lines.append(prompt.question)
    if prompt.examples:
        lines.append("")
        lines.append("Examples:")
        for index, example in enumerate(prompt.examples, start=1):
            lines.append(f"{index}. {example}")
    lines.append("")
    lines.append("You can also use /help, /status, /back, /skip, /done, or /submit.")
    return "\n".join(lines)


def _render_synthesis_markdown(
    synthesis: dict[str, Any],
    expansion_response: Any = None,
) -> str:
    search_optimized = synthesis.get("search_optimized")
    semantic_statement = getattr(search_optimized, "semantic", "") if search_optimized else ""
    keyword = getattr(search_optimized, "keyword", None) if search_optimized else None
    boolean_query = getattr(keyword, "structured", "") if keyword else ""

    lines = [
        "## Refined Query",
        f"**Clarified query**\n{synthesis.get('clarified_query', '')}",
        f"**Semantic statement**\n{semantic_statement}",
        f"**Keyword statement**\n{synthesis.get('keyword_statement', '')}",
        f"**Boolean search construction**\n{boolean_query}",
    ]

    filters = synthesis.get("search_filters")
    if filters:
        publication_years = getattr(filters, "publication_years", None)
        publication_types = getattr(filters, "publication_types", None)
        if publication_years or publication_types:
            lines.append("**Suggested filters**")
            if publication_years:
                lines.append(f"- Years: {publication_years}")
            if publication_types:
                lines.append(f"- Types: {', '.join(publication_types)}")

    if expansion_response and getattr(expansion_response, "levels", None):
        lines.append("**Search expansion levels**")
        if getattr(expansion_response, "recommended_starting_level", None):
            lines.append(
                f"- Recommended starting level: {expansion_response.recommended_starting_level}"
            )
        for level in expansion_response.levels:
            lines.append(f"- Level {level.level} ({level.label}): {level.search_query}")

    return "\n\n".join(lines)


async def _generate_expansion(synthesis: dict[str, Any]) -> Any:
    manager = get_refinement_manager()
    search_input = build_search_expansion_input_from_synthesis(synthesis)
    if search_input is None:
        return None
    expansion_response, _ = await manager.generate_search_expansion_levels(search_input=search_input)
    return expansion_response


async def _send_message(content: str) -> None:
    await cl.Message(content=content).send()


async def _handle_framework_selection(state: ChainlitWorkflowState, text: str) -> None:
    names = _framework_names()
    if text not in names:
        await _send_message(
            f"Unknown framework '{text}'.\n\n{_framework_help_text()}"
        )
        return
    state.framework_name = text
    await _send_message(
        f"Framework set to **{text}**. Send your initial research question to start refinement."
    )


async def _start_refinement_session(state: ChainlitWorkflowState, text: str) -> None:
    framework = registry.get_framework(state.framework_name)
    service = _get_interactive_service()
    state.original_query = text
    state.session = service.start_session(original_query=text, refinement_framework=framework)
    state.prompt = await service.get_next_prompt(state.session)
    if state.prompt is None:
        synthesis = await service.synthesize(state.session)
        expansion = await _generate_expansion(synthesis)
        await _send_message(_render_synthesis_markdown(synthesis, expansion))
        state.session = None
        return
    await _send_message(_format_prompt(state.prompt))


async def _continue_refinement(state: ChainlitWorkflowState, text: str) -> None:
    service = _get_interactive_service()
    current_examples = state.prompt.examples if state.prompt else None
    resolved_input, was_numeric = resolve_numeric_examples(text, current_examples)
    turn_result = await service.submit_input(
        session=state.session,
        user_input=resolved_input,
        selected_example=was_numeric,
    )

    if turn_result.message:
        await _send_message(turn_result.message)

    next_prompt = turn_result.prompt
    if next_prompt is None and not state.session.synthesis_requested:
        next_prompt = await service.get_next_prompt(state.session)

    state.prompt = next_prompt
    if state.session.synthesis_requested or next_prompt is None:
        synthesis = await service.synthesize(state.session)
        expansion = await _generate_expansion(synthesis)
        await _send_message(_render_synthesis_markdown(synthesis, expansion))
        state.session = None
        state.prompt = None
        await _send_message(
            f"Send another research question to start a new **{state.framework_name}** session, or send a different framework name to switch frameworks."
        )
        return

    await _send_message(_format_prompt(next_prompt))


if cl is not None:
    @cl.on_chat_start
    async def on_chat_start() -> None:
        registry.reload_from_env(raise_on_error=False)
        cl.user_session.set("workflow_state", ChainlitWorkflowState())
        await _send_message(_framework_help_text())


    @cl.on_message
    async def on_message(message: "cl.Message") -> None:
        state: ChainlitWorkflowState = cl.user_session.get("workflow_state")
        if state is None:
            state = ChainlitWorkflowState()
            cl.user_session.set("workflow_state", state)

        text = (message.content or "").strip()
        if not text:
            await _send_message("Send a framework name or a research question.")
            return

        if text == "/frameworks":
            await _send_message(_framework_help_text())
            return

        if state.session is None and text in _framework_names():
            state.framework_name = None

        if state.framework_name is None:
            await _handle_framework_selection(state, text)
            return

        if state.session is None:
            await _start_refinement_session(state, text)
            return

        await _continue_refinement(state, text)


else:
    async def on_chat_start() -> None:  # pragma: no cover
        raise RuntimeError("Chainlit is not installed. Add the optional dependency to run the chat UI.")


    async def on_message(message) -> None:  # pragma: no cover
        raise RuntimeError("Chainlit is not installed. Add the optional dependency to run the chat UI.")