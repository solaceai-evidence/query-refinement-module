"""Chainlit chat UI for schema-guided query refinement.

The UI is a thin layer over ``ChainlitRefinementAdapter``, which runs the same
persisted workflow as the REST API. Chat state only holds identifiers; the
database and session manager hold the workflow itself, so every session is
access-controlled, audited, traceable and resumable.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.application.chainlit_adapter import ChainlitRefinementAdapter
from query_refinement_module.application.feedback_survey import (
    SurveyResponses,
    apply_survey_answer,
    build_survey_steps,
    survey_items,
)
from query_refinement_module.application.interactive_refinement_helpers import resolve_numeric_examples
from query_refinement_module.schema import registry

try:
    import chainlit as cl
except ImportError:  # pragma: no cover - import-safe for environments without Chainlit
    cl = None


# (command, label) in the order shown under each question
COMMAND_BUTTONS = [
    ("/back", "◀ Back"),
    ("/skip", "Skip"),
    ("/done", "Done with this"),
    ("/submit", "Finish & synthesize"),
    ("/status", "Status"),
    ("/steps", "Steps"),
    ("/help", "Help"),
    ("/clear", "Clear answer"),
    ("/restart", "Restart"),
]

CONFIRM_COMMANDS = {
    "/restart": "Restart refinement from the first dimension? Answers given so far will be cleared.",
    "/clear": "Clear the current answer for this dimension?",
    "/submit": "Finish now and synthesize with the information captured so far?",
}

EXAMPLE_LABEL_MAX = 80


class ChatState:
    """Per-chat identifiers; the workflow itself lives in the DB and session store.

    A plain class rather than a dataclass: Chainlit loads this file without
    registering it in ``sys.modules``, which breaks ``@dataclass``.
    """

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.framework_name: Optional[str] = None
        self.query_id: Optional[int] = None
        self.session_id: Optional[int] = None
        self.prompt: Optional[Dict[str, Any]] = None
        self.feedback_done: Set[int] = set()
        self.live_actions: List[Any] = []
        # Active feedback survey: {"steps": [...], "index": int, "responses": SurveyResponses}
        self.survey: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------
# Pure formatting helpers
# ----------------------------------------------------------------------

def format_prompt(prompt: Dict[str, Any]) -> str:
    lines = [f"### {prompt.get('name') or prompt.get('aspect_name') or 'Next question'}"]
    if prompt.get("description"):
        lines.append(f"_{prompt['description']}_")
    lines.append("")
    lines.append(prompt.get("question") or "")
    examples = prompt.get("examples") or []
    if examples:
        lines.append("")
        lines.append("**Suggested answers** (click one, type its number, or write your own):")
        lines.extend(f"{index}. {example}" for index, example in enumerate(examples, start=1))
    return "\n".join(lines)


def format_step_list(steps: List[Dict[str, Any]]) -> str:
    icons = {"completed": "✅", "active": "▶️", "needs review": "⚠️", "not started": "○"}
    lines = ["**Refinement steps**"]
    for index, step in enumerate(steps, start=1):
        status = "skipped" if step.get("was_skipped") else step.get("status", "")
        icon = "⏭️" if status == "skipped" else icons.get(status, "○")
        lines.append(f"{index}. {icon} {step.get('name')} — {status}")
    return "\n".join(lines)


def format_command_result(payload: Dict[str, Any]) -> str:
    parts = []
    if payload.get("step_list"):
        parts.append(format_step_list(payload["step_list"]))
    elif payload.get("message"):
        parts.append(payload["message"])
    summary = payload.get("step_summary")
    if isinstance(summary, dict) and not payload.get("message"):
        parts.append("\n".join(f"- {key.replace('_', ' ')}: {value}" for key, value in summary.items()))
    return "\n\n".join(parts) or f"/{payload.get('command_type')} done."


def task_state(aspect: Dict[str, Any]) -> str:
    """Map an aspect status payload to a TaskStatus name."""
    if aspect.get("was_skipped"):
        return "DONE"
    return {
        "completed": "DONE",
        "active": "RUNNING",
        "needs review": "FAILED",
    }.get(aspect.get("status", ""), "READY")


def task_title(aspect: Dict[str, Any]) -> str:
    suffix = " (skipped)" if aspect.get("was_skipped") else (" (needs review)" if aspect.get("status") == "needs review" else "")
    return f"{aspect.get('name')}{suffix}"


def role_label(role: str) -> str:
    """Turn a query_role id such as 'intervention_or_exposure' into 'Intervention / exposure'."""
    words = (role or "concept").replace("_or_", " / ").replace("_", " ")
    return words[:1].upper() + words[1:]


def _section(title: str, body: Optional[str]) -> Optional[str]:
    return f"**{title}**\n{body}" if body else None


def render_synthesis_markdown(synthesis: Dict[str, Any]) -> str:
    structured = synthesis.get("structured_output") or {}
    search_optimized = structured.get("search_optimized") or {}
    keyword = search_optimized.get("keyword") or {}
    filters = structured.get("search_filters") or {}
    dimensions = structured.get("dimensions_specifications") or {}

    sections = [
        "## Refined research question",
        synthesis.get("clarified_query") or "",
    ]
    if dimensions:
        labels = structured.get("dimension_labels") or {}
        lines = [f"- **{labels.get(key, key)}**: {value}" for key, value in dimensions.items() if value]
        skipped = [labels.get(key, key) for key, value in dimensions.items() if not value]
        if skipped:
            lines.append(f"- _Not specified: {', '.join(skipped)}_")
        sections.append("**Structured statement**\n" + "\n".join(lines))
    sections.append(_section("Semantic search statement", search_optimized.get("semantic")))
    sections.append(_section("Keyword statement", structured.get("keyword_statement")))
    if keyword.get("structured"):
        sections.append(f"**Boolean search construction**\n```text\n{keyword['structured']}\n```")
    sections.append(render_search_validation(synthesis))

    filter_lines = []
    if filters.get("publication_years"):
        filter_lines.append(f"- Years: {filters['publication_years']}")
    if filters.get("publication_types"):
        filter_lines.append(f"- Types: {', '.join(filters['publication_types'])}")
    if filter_lines:
        sections.append("**Suggested filters**\n" + "\n".join(filter_lines))

    levels = synthesis.get("expansion_levels") or []
    if levels:
        meta = synthesis.get("expansion_metadata") or {}
        level_lines = [f"- Level {level.get('level')}: {level.get('label')}" for level in levels]
        if meta.get("recommended_starting_level") is not None:
            level_lines.append(f"\nRecommended starting level: **{meta['recommended_starting_level']}**")
            if meta.get("recommendation_rationale"):
                level_lines.append(f"_{meta['recommendation_rationale']}_")
        sections.append("**Search expansion levels** (full queries in the side panel)\n" + "\n".join(level_lines))

    return "\n\n".join(section for section in sections if section)


_REPAIR_REASONS = {
    "redundant": "it only restated another concept",
    "ungrounded": "it was not based on anything you said",
}


def render_search_validation(synthesis: Dict[str, Any]) -> Optional[str]:
    """Summarise the deterministic search checks and any automatic repairs."""
    quality = (synthesis.get("structured_output") or {}).get("search_quality")
    if not quality:
        return None
    final = quality.get("final") or {}
    lines = []
    for repair in quality.get("repairs") or []:
        reason = _REPAIR_REASONS.get(repair.get("reason"), repair.get("reason"))
        lines.append(f"- Removed the *{role_label(repair.get('role') or 'concept')}* block because {reason}; this can only widen the search.")
    problems = []
    if final.get("syntax_problems"):
        problems.append("syntax: " + ", ".join(final["syntax_problems"]))
    if not final.get("aligned", True):
        problems.append("concept blocks do not match the Boolean query")
    if final.get("ungrounded_blocks"):
        problems.append(f"{len(final['ungrounded_blocks'])} block(s) not obviously grounded in your question — please check")
    if final.get("leaked_terms"):
        problems.append("broader or informal terms in the core query: " + ", ".join(t for v in final["leaked_terms"].values() for t in v))
    lines.extend(f"- ⚠️ {problem}" for problem in problems)
    status = "✅ Passed all checks" if final.get("search_ready") else "⚠️ Review suggested"
    checks = "syntax, block alignment, redundancy, grounding in your input, term leakage"
    return f"**Search validation** — {status} ({checks}; {final.get('block_count', '?')} concept blocks)" + ("\n" + "\n".join(lines) if lines else "")


def render_concept_blocks(synthesis: Dict[str, Any]) -> Optional[str]:
    structured = synthesis.get("structured_output") or {}
    keyword = (structured.get("search_optimized") or {}).get("keyword") or {}
    blocks = keyword.get("combined_blocks") or []
    if not blocks:
        return None
    lines = ["# Concept blocks", ""]
    for index, block in enumerate(blocks, start=1):
        lines.append(f"## {index}. {role_label(block.get('role', 'concept'))}")
        if block.get("free_text"):
            lines.append("Free text: " + " OR ".join(block["free_text"]))
        for vocabulary, terms in (block.get("controlled_vocabulary") or {}).items():
            if terms:
                lines.append(f"{vocabulary}: " + "; ".join(terms))
        lines.append("")
    return "\n".join(lines)


def render_expansion_levels(synthesis: Dict[str, Any]) -> Optional[str]:
    levels = synthesis.get("expansion_levels") or []
    if not levels:
        return None
    lines = ["# Search expansion levels", ""]
    for level in levels:
        lines.append(f"## Level {level.get('level')}: {level.get('label')}")
        if level.get("query"):
            lines.append(f"_{level['query']}_")
        lines.append(f"```text\n{level.get('boolean_query', '')}\n```")
        lines.append("")
    return "\n".join(lines)


def build_markdown_export(export: Dict[str, Any]) -> str:
    lines = [
        f"# Query refinement — query {export['query_id']}",
        "",
        f"- Framework: {export.get('framework')}",
        f"- Exported: {export.get('exported_at')}",
        f"- Original question: {export.get('original_query')}",
        "",
        render_synthesis_markdown(export.get("synthesis") or {}),
        "",
        "## Refinement trace",
    ]
    for step in export.get("refinement_trace") or []:
        status = "skipped" if step.get("was_skipped") else ("complete" if step.get("is_complete") else "incomplete")
        lines.append(f"### {step.get('aspect_name')} ({status})")
        for turn in step.get("turns") or []:
            lines.append(f"- **Q:** {turn.get('question')}")
            lines.append(f"  **A:** {turn.get('answer')}")
        if step.get("final_value"):
            lines.append(f"- **Accepted value:** {step['final_value']}")
        lines.append("")
    for extra in (render_concept_blocks(export.get("synthesis") or {}), render_expansion_levels(export.get("synthesis") or {})):
        if extra:
            # demote headings one level inside the report
            lines.append("\n".join("#" + line if line.startswith("#") else line for line in extra.splitlines()))
    return "\n".join(lines)


def help_text() -> str:
    return (
        "**Controls** — use the buttons under each question, or type:\n"
        "- `/back` (`/prev`) revisit the previous dimension\n"
        "- `/skip` skip this dimension\n"
        "- `/done` accept what you have for this dimension and move on\n"
        "- `/clear` clear the answer for this dimension\n"
        "- `/restart` start the refinement again\n"
        "- `/submit` (`/end`) finish now and synthesize\n"
        "- `/status`, `/steps`, `/help` show progress and help\n"
        "- `/frameworks` choose a different framework"
    )


# ----------------------------------------------------------------------
# Chainlit handlers
#
# Action callbacks never await AskActionMessage/AskUserMessage: in Chainlit
# 2.x that leaves the UI stuck in a "running" state. Confirmations and the
# feedback survey are therefore driven by follow-up actions and messages.
# ----------------------------------------------------------------------

if cl is not None:

    def _state() -> Optional[ChatState]:
        return cl.user_session.get("chat_state")

    async def _send(content: str, *, actions=None, elements=None) -> Any:
        message = cl.Message(content=content, actions=actions or [], elements=elements or [])
        await message.send()
        return message

    async def _send_with_actions(state: ChatState, content: str, actions: List[Any], *, elements=None) -> None:
        """Send a message whose buttons are retired as soon as the user moves on."""
        await _clear_live_actions(state)
        await _send(content, actions=actions, elements=elements)
        state.live_actions = list(actions)

    async def _echo_user(content: str) -> None:
        user = cl.user_session.get("user")
        await cl.Message(content=content, author=getattr(user, "identifier", "You"), type="user_message").send()

    class _Handled(Exception):
        """Raised after an error has already been shown to the user."""

    @asynccontextmanager
    async def _workflow():
        """Yield an adapter and the DB-bound user; report workflow errors in chat."""
        state = _state()
        try:
            with ChainlitRefinementAdapter.open() as adapter:
                yield adapter, adapter.get_user(state.user_id)
        except QueryRefinementException as exc:
            await _send(f"⚠️ {exc.message}")
            raise _Handled() from exc

    async def _clear_live_actions(state: ChatState) -> None:
        for action in state.live_actions:
            try:
                await action.remove()
            except Exception:  # pragma: no cover - action may already be gone
                pass
        state.live_actions = []

    async def _ask_confirmation(state: ChatState, question: str, intent: Dict[str, Any]) -> None:
        """Ask a yes/no question; ``on_confirm`` carries out ``intent`` on yes."""
        await _send_with_actions(
            state,
            question,
            [
                cl.Action(name="confirm", payload={**intent, "ok": True}, label="Yes, continue"),
                cl.Action(name="confirm", payload={"ok": False}, label="Cancel"),
            ],
        )

    @cl.action_callback("confirm")
    async def on_confirm(action) -> None:
        state = _state()
        if state is None:
            return
        await _clear_live_actions(state)
        intent = action.payload
        if not intent.get("ok"):
            await _send("Cancelled.")
            if state.prompt:
                await _show_prompt(state, state.prompt)
            return
        if intent.get("kind") == "command":
            await _submit(state, intent["command"], force=bool(intent.get("force")))
        elif intent.get("kind") == "switch_framework":
            await _select_framework(state, intent["framework"])

    # ---------------- login, framework selection and resume ----------------

    @cl.data_layer
    def no_chainlit_data_layer():
        # Chainlit would otherwise build its own data layer from DATABASE_URL.
        # The app database (via the adapter) is the system of record instead.
        return None

    @cl.password_auth_callback
    async def auth_callback(username: str, password: str):
        with ChainlitRefinementAdapter.open() as adapter:
            user = adapter.authenticate(username, password)
            if user is None:
                return None
            return cl.User(
                identifier=user.username,
                metadata={"user_id": user.id, "role": "admin" if user.is_superuser else "user"},
            )

    async def _send_framework_picker(state: ChatState, frameworks: List[str]) -> None:
        if not frameworks:
            await _send("No refinement frameworks are assigned to your account. Please contact an administrator.")
            return
        actions = [cl.Action(name="select_framework", payload={"framework": name}, label=name) for name in frameworks]
        await _send_with_actions(state, "**Choose a refinement framework** to structure your question:", actions)

    def _resume_payload(resumable: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "query_id": resumable["query_id"],
            "session_id": resumable["session_id"],
            "framework": resumable["framework_name"],
        }

    @cl.on_chat_start
    async def on_chat_start() -> None:
        registry.reload_from_env(raise_on_error=False)
        user = cl.user_session.get("user")
        if user is None or "user_id" not in (user.metadata or {}):
            await _send("Login is required. Set `CHAINLIT_AUTH_SECRET` and restart the app.")
            return

        state = ChatState(user_id=user.metadata["user_id"])
        cl.user_session.set("chat_state", state)
        try:
            async with _workflow() as (adapter, db_user):
                if adapter.workflow_limit_reached(db_user):
                    await _send("You have already completed a refinement workflow. Thank you for your participation!")
                    return
                frameworks = adapter.list_frameworks(db_user)
                resumable = adapter.find_resumable_query(db_user)
        except _Handled:
            return

        await _send(
            f"## Query refinement\n\nWelcome, **{user.identifier}**. I'll help you turn a free-text question "
            "into a structured, search-ready statement through a short guided dialogue.\n\n" + help_text()
        )
        if resumable and resumable["framework_name"] in frameworks:
            payload = _resume_payload(resumable)
            actions = [
                cl.Action(name="resume_query", payload=payload, label="Resume it"),
                cl.Action(name="discard_query", payload=payload, label="Discard and start fresh"),
            ]
            await _send_with_actions(
                state,
                f"You have an unfinished query using **{resumable['framework_name']}**:\n\n> {resumable['original_query']}",
                actions,
            )
            return
        await _send_framework_picker(state, frameworks)

    async def _select_framework(state: ChatState, framework_name: str) -> None:
        await _clear_live_actions(state)
        state.framework_name = framework_name
        state.query_id = state.session_id = None
        state.prompt = None
        cl.user_session.set("task_list", None)
        await _send(f"Framework set to **{framework_name}**. Now send your initial research question.")

    @cl.action_callback("select_framework")
    async def on_select_framework(action) -> None:
        state = _state()
        if state is None:
            return
        framework = action.payload["framework"]
        if state.query_id is not None:
            await _ask_confirmation(
                state,
                f"Leave the current refinement and switch to **{framework}**? You can resume it later.",
                {"kind": "switch_framework", "framework": framework},
            )
            return
        await _select_framework(state, framework)

    @cl.action_callback("resume_query")
    async def on_resume(action) -> None:
        state = _state()
        await _clear_live_actions(state)
        try:
            async with _workflow() as (adapter, user):
                payload = await adapter.resume(user, query_id=action.payload["query_id"])
        except _Handled:
            return
        state.framework_name = action.payload["framework"]
        state.query_id = action.payload["query_id"]
        state.session_id = action.payload["session_id"]
        await _send(f"Resumed your **{state.framework_name}** refinement.")
        await _after_turn(state, payload)

    @cl.action_callback("discard_query")
    async def on_discard(action) -> None:
        state = _state()
        await _clear_live_actions(state)
        try:
            async with _workflow() as (adapter, user):
                await adapter.abandon(user, session_id=action.payload["session_id"])
                frameworks = adapter.list_frameworks(user)
        except _Handled:
            return
        await _send("Discarded the unfinished query.")
        await _send_framework_picker(state, frameworks)

    # ---------------- refinement turns ----------------

    async def _start(state: ChatState, text: str) -> None:
        await _clear_live_actions(state)
        async with cl.Step(name="Analysing your question", type="run"):
            try:
                async with _workflow() as (adapter, user):
                    payload = await adapter.start(user, framework_name=state.framework_name, original_query=text)
            except _Handled:
                return
        state.query_id = payload["query_id"]
        state.session_id = payload["session_id"]
        cl.user_session.set("task_list", None)
        await _after_turn(state, payload)

    async def _submit(state: ChatState, text: str, *, force: bool = False) -> None:
        await _clear_live_actions(state)
        async with cl.Step(name="Thinking", type="run"):
            try:
                async with _workflow() as (adapter, user):
                    payload = await adapter.submit(user, query_id=state.query_id, text=text, force=force)
            except _Handled:
                return
        if payload.get("force_required"):
            await _ask_confirmation(
                state,
                payload.get("message") or "This will invalidate dependent answers. Continue?",
                {"kind": "command", "command": text, "force": True},
            )
            return
        await _after_turn(state, payload)

    async def _request_command(state: ChatState, command: str) -> None:
        """Run a command, asking for confirmation first when it is destructive."""
        if command in CONFIRM_COMMANDS:
            await _ask_confirmation(state, CONFIRM_COMMANDS[command], {"kind": "command", "command": command})
            return
        await _submit(state, command)

    async def _show_prompt(state: ChatState, prompt: Dict[str, Any]) -> None:
        state.prompt = prompt
        actions = [
            cl.Action(name="example", payload={"text": example}, label=_truncate(example))
            for example in (prompt.get("examples") or [])
        ]
        actions += [cl.Action(name="command", payload={"command": cmd}, label=label) for cmd, label in COMMAND_BUTTONS]
        await _send_with_actions(state, format_prompt(prompt), actions)

    async def _after_turn(state: ChatState, payload: Dict[str, Any]) -> None:
        if "command_type" in payload:
            await _send(format_command_result(payload))

        if payload.get("ready_for_synthesis") or payload.get("synthesis_ready"):
            await _synthesize(state)
            return

        if payload.get("next_prompt"):
            await _show_prompt(state, payload["next_prompt"])
        await _refresh_progress(state)

    def _truncate(text: str) -> str:
        return text if len(text) <= EXAMPLE_LABEL_MAX else text[: EXAMPLE_LABEL_MAX - 1] + "…"

    async def _refresh_progress(state: ChatState) -> None:
        if state.query_id is None:
            return
        try:
            async with _workflow() as (adapter, user):
                status = await adapter.status(user, query_id=state.query_id)
        except _Handled:
            return
        aspects = status.get("aspects") or []
        if not aspects:
            return
        task_list = cl.user_session.get("task_list") or cl.TaskList()
        task_list.tasks = [cl.Task(title=task_title(a), status=getattr(cl.TaskStatus, task_state(a))) for a in aspects]
        done = sum(1 for a in aspects if task_state(a) == "DONE")
        task_list.status = f"{done}/{len(aspects)} dimensions captured"
        await task_list.send()
        cl.user_session.set("task_list", task_list)

    async def _synthesize(state: ChatState) -> None:
        await _clear_live_actions(state)
        query_id = state.query_id
        async with cl.Step(name="Synthesizing structured statement and search strategy", type="run"):
            try:
                async with _workflow() as (adapter, user):
                    synthesis = await adapter.synthesize(user, query_id=query_id)
                    export = adapter.build_export(user, query_id=query_id, synthesis=synthesis)
            except _Handled:
                return

        task_list = cl.user_session.get("task_list")
        if task_list is not None:
            for task in task_list.tasks:
                task.status = cl.TaskStatus.DONE
            task_list.status = "Synthesis complete"
            await task_list.send()

        elements = [
            cl.File(
                name=f"query-refinement-{query_id}.json",
                content=json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8"),
                mime="application/json",
                display="inline",
            ),
            cl.File(
                name=f"query-refinement-{query_id}.md",
                content=build_markdown_export(export).encode("utf-8"),
                mime="text/markdown",
                display="inline",
            ),
        ]
        details = "\n\n".join(part for part in (render_concept_blocks(synthesis), render_expansion_levels(synthesis)) if part)
        if details:
            elements.append(cl.Text(name="Search details", content=details, display="side"))

        await _send(
            render_synthesis_markdown(synthesis)
            + "\n\n📎 Download the structured output (JSON, for downstream tools) or a readable report (Markdown) below."
            + ("\n\nOpen **Search details** for per-concept search terms and the full expansion queries." if details else ""),
            elements=elements,
        )
        state.query_id = state.session_id = None
        state.prompt = None

        actions = [cl.Action(name="new_query", payload={}, label="Refine another question")]
        if query_id not in state.feedback_done:
            actions.insert(0, cl.Action(
                name="start_feedback",
                payload={"query_id": query_id, "framework": state.framework_name},
                label="Give feedback (2 min)",
            ))
        await _send_with_actions(state, "What next?", actions)

    @cl.action_callback("example")
    async def on_example(action) -> None:
        state = _state()
        if state is None or state.query_id is None:
            return
        await _echo_user(action.payload["text"])
        await _submit(state, action.payload["text"])

    @cl.action_callback("command")
    async def on_command(action) -> None:
        state = _state()
        if state is None or state.query_id is None:
            return
        await _echo_user(action.payload["command"])
        await _request_command(state, action.payload["command"])

    @cl.action_callback("new_query")
    async def on_new_query(action) -> None:
        state = _state()
        await _clear_live_actions(state)
        if state.framework_name:
            await _send(f"Send another research question to refine with **{state.framework_name}**, or pick a different framework.")
        try:
            async with _workflow() as (adapter, user):
                frameworks = adapter.list_frameworks(user)
        except _Handled:
            return
        await _send_framework_picker(state, frameworks)

    # ---------------- feedback survey (step-by-step) ----------------

    async def _survey_ask(state: ChatState) -> None:
        survey = state.survey
        step = survey["steps"][survey["index"]]
        progress = f"_Question {survey['index'] + 1} of {len(survey['steps'])}_\n\n"
        if step["kind"] == "text":
            await _clear_live_actions(state)
            await _send(progress + step["question"])
            return
        actions = [cl.Action(name="survey_answer", payload={"value": value}, label=label) for value, label in step["options"]]
        if step.get("skippable"):
            actions.append(cl.Action(name="survey_answer", payload={"value": None}, label="Skip"))
        await _send_with_actions(state, progress + step["question"], actions)

    async def _survey_record(state: ChatState, value: Any) -> None:
        survey = state.survey
        apply_survey_answer(survey["responses"], survey["steps"][survey["index"]], value)
        survey["index"] += 1
        if survey["index"] < len(survey["steps"]):
            await _survey_ask(state)
            return

        responses = survey["responses"]
        state.survey = None
        await _clear_live_actions(state)
        try:
            async with _workflow() as (adapter, user):
                adapter.save_feedback(
                    user,
                    query_id=responses.query_id,
                    rating=responses.rating,
                    comments=responses.comments(),
                    metadata=responses.to_metadata(),
                    consent=bool(responses.consent),
                )
        except _Handled:
            return
        state.feedback_done.add(responses.query_id)
        await _send_with_actions(
            state,
            "Thank you — your feedback has been recorded.",
            [cl.Action(name="new_query", payload={}, label="Refine another question")],
        )

    @cl.action_callback("start_feedback")
    async def on_start_feedback(action) -> None:
        state = _state()
        query_id = action.payload["query_id"]
        if state is None or query_id in state.feedback_done or state.survey is not None:
            return
        framework = action.payload.get("framework")
        state.survey = {
            "steps": build_survey_steps(framework),
            "index": 0,
            "responses": SurveyResponses(framework_name=framework, query_id=query_id),
        }
        await _clear_live_actions(state)
        await _send(f"### Feedback\n{survey_items(framework)['intro']}")
        await _survey_ask(state)

    @cl.action_callback("survey_answer")
    async def on_survey_answer(action) -> None:
        state = _state()
        if state is None or state.survey is None:
            return
        await _echo_user(action.label)
        await _survey_record(state, action.payload.get("value"))

    # ---------------- free-text input ----------------

    @cl.on_message
    async def on_message(message) -> None:
        state = _state()
        if state is None:
            await _send("Please reload the page and log in.")
            return

        text = (message.content or "").strip()

        if state.survey is not None:
            step = state.survey["steps"][state.survey["index"]]
            if step["kind"] == "text":
                await _survey_record(state, text)
            else:
                await _send("Please choose one of the options above (or **Skip**).")
            return

        if not text:
            await _send("Send a research question, an answer, or a command such as `/help`.")
            return

        if text == "/frameworks":
            try:
                async with _workflow() as (adapter, user):
                    frameworks = adapter.list_frameworks(user)
            except _Handled:
                return
            await _send_framework_picker(state, frameworks)
            return

        if state.query_id is None:
            try:
                async with _workflow() as (adapter, user):
                    frameworks = adapter.list_frameworks(user)
            except _Handled:
                return
            if text in frameworks:
                await _select_framework(state, text)
                return
            if state.framework_name is None:
                await _send("Please choose a framework first.")
                await _send_framework_picker(state, frameworks)
                return
            if text.startswith("/"):
                await _send("Commands apply during refinement. Send a research question to begin.")
                return
            await _start(state, text)
            return

        if text.lower() in CONFIRM_COMMANDS:
            await _request_command(state, text.lower())
            return
        examples = (state.prompt or {}).get("examples")
        resolved, _ = resolve_numeric_examples(text, examples)
        await _submit(state, resolved)
