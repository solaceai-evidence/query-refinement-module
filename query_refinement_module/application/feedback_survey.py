"""Post-synthesis usability survey shared by the chat UI.

Item wording and metadata keys match the survey used by the previous web
frontend so that responses collected before and after the Chainlit migration
can be analysed together.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

LIKERT_AGREE = ("Strongly disagree", "Strongly agree")
LIKERT_EASE = ("Very difficult", "Very easy")

_DEFAULT_ITEMS = {
    "intro": "This short survey helps us improve the tool. Your responses support research on AI-assisted research question refinement.",
    "overall_helpful": "Overall, I would rate this tool as helpful for clarifying my research question.",
    "confidence_before": "Before using the tool, I felt confident about the clarity and specificity of my research question.",
    "confidence_after": "After using the tool, I feel confident about the clarity and specificity of my research question.",
    "question_quality": "The questions asked by the chatbot were relevant and improved my thinking.",
    "new_parameters_prompting": "To what extent did the chatbot prompt you to consider new parameters for your research question?",
    "ease_of_use": "The tool was easy to use.",
    "felt_in_control": "I felt in control of the refinement process (e.g., could revise/skip/finish when needed).",
}

_FRAMEWORK_ITEMS = {
    "pico_advanced": {
        "intro": "This short survey is for systematic reviewers using the PICO refinement framework. Your responses help improve the tool and support research on AI-assisted evidence synthesis.",
        "overall_helpful": "Overall, I would rate this tool as helpful for structuring my systematic review question.",
        "confidence_before": "Before using the tool, I felt confident about the precision of my PICO question.",
        "confidence_after": "After using the tool, I feel confident about the precision of my PICO question.",
        "question_quality": "The questions asked by the chatbot were relevant and helped sharpen my PICO elements.",
        "new_parameters_prompting": "To what extent did the chatbot prompt you to consider PICO elements you had not previously defined?",
    },
    "mph_dissertation": {
        "intro": "This short survey is part of the MPH student workflow. Your responses help improve the tool and support research on AI-assisted dissertation planning.",
        "overall_helpful": "Overall, I would rate this tool as helpful for clarifying my dissertation topic.",
        "confidence_before": "Before using the tool, I felt confident about the clarity/specificity of my dissertation topic.",
        "confidence_after": "After using the tool, I feel confident about the clarity/specificity of my dissertation topic.",
        "question_quality": "The questions asked by the chatbot were relevant and improved my thinking about my dissertation.",
    },
}

# (key, scale labels); "overall_helpful" is stored as the top-level feedback rating
LIKERT_ITEMS: List[Tuple[str, Tuple[str, str]]] = [
    ("overall_helpful", LIKERT_AGREE),
    ("confidence_before", LIKERT_AGREE),
    ("confidence_after", LIKERT_AGREE),
    ("question_quality", LIKERT_AGREE),
    ("new_parameters_prompting", LIKERT_AGREE),
    ("ease_of_use", LIKERT_EASE),
    ("felt_in_control", LIKERT_AGREE),
]

TIME_SAVED_OPTIONS = [
    ("none", "No time saved"),
    ("a_little", "A little"),
    ("some", "Some"),
    ("a_lot", "A lot"),
]

TONE_OPTIONS = [
    ("educational", "Educational", "Encouraging, explains the rationale, and uses examples."),
    ("professional", "Professional", "Direct, concise, and focused on clear specifications."),
    ("pragmatic", "Pragmatic", "Practical, feasibility-focused, and action oriented."),
]

COMPLEXITY_OPTIONS = [
    ("novice", "Novice", "Defines terms, keeps explanations simple, and checks understanding."),
    ("intermediate", "Intermediate", "Uses standard research terms with brief context when needed."),
    ("advanced", "Advanced", "Uses technical language and discusses tradeoffs."),
    ("expert", "Expert", "Peer-level language with critical, methodological pushback."),
]

FREE_TEXT_ITEMS = [
    ("most_helpful", "What was the most helpful part of the experience?"),
    ("improvements", "What should we improve?"),
    ("other", "Anything else you'd like to add?"),
]

CONSENT_QUESTION = (
    "**Consent to retain your data.** May we keep your query, the refinement dialogue and "
    "these answers for research on AI-assisted query formulation? If you choose *No*, your "
    "data is excluded from analysis and may be removed by the retention policy."
)


def survey_items(framework_name: Optional[str]) -> Dict[str, str]:
    """Return item wording for a framework, falling back to the generic wording."""
    return {**_DEFAULT_ITEMS, **_FRAMEWORK_ITEMS.get(framework_name or "", {})}


@dataclass
class SurveyResponses:
    framework_name: Optional[str]
    query_id: int
    likert: Dict[str, Optional[int]] = field(default_factory=dict)
    time_saved: Optional[str] = None
    tone: Optional[str] = None
    complexity: Optional[str] = None
    free_text: Dict[str, Optional[str]] = field(default_factory=dict)
    consent: Optional[bool] = None

    @property
    def rating(self) -> Optional[int]:
        return self.likert.get("overall_helpful")

    def comments(self) -> Optional[str]:
        labels = {"most_helpful": "Most helpful", "improvements": "Improvements", "other": "Other"}
        parts = [f"{labels[key]}: {value}" for key, value in self.free_text.items() if value]
        return "\n".join(parts) or None

    def to_metadata(self) -> Dict[str, Any]:
        survey_key = f"{self.framework_name or 'generic'}_survey_v1"
        return {
            survey_key: {
                "time_saved": self.time_saved,
                **{key: self.likert.get(key) for key, _ in LIKERT_ITEMS if key != "overall_helpful"},
                "tone_selected": self.tone,
                "complexity_selected": self.complexity,
            },
            "consent": {"selection": None if self.consent is None else ("yes" if self.consent else "no")},
            "free_text": {key: self.free_text.get(key) for key, _ in FREE_TEXT_ITEMS},
            "ui_context": {"query_id": self.query_id, "client": "chainlit"},
        }


def build_survey_steps(framework_name: Optional[str]) -> List[Dict[str, Any]]:
    """Ordered survey steps; ``kind`` is ``choice`` (buttons) or ``text`` (typed reply)."""
    items = survey_items(framework_name)
    steps: List[Dict[str, Any]] = []
    for key, (low, high) in LIKERT_ITEMS:
        steps.append({
            "kind": "choice",
            "key": key,
            "question": f"**{items[key]}**\n_1 = {low} · 5 = {high}_",
            "options": [(n, str(n)) for n in range(1, 6)],
            "skippable": True,
        })
    steps.append({
        "kind": "choice",
        "key": "time_saved",
        "question": "**How much time did this tool save you overall?**",
        "options": [(value, label) for value, label in TIME_SAVED_OPTIONS],
        "skippable": True,
    })
    for key, title, options in (
        ("tone", "Which tone would you prefer for the questions?", TONE_OPTIONS),
        ("complexity", "Which level of complexity would suit you best?", COMPLEXITY_OPTIONS),
    ):
        steps.append({
            "kind": "choice",
            "key": key,
            "question": f"**{title}**\n" + "\n".join(f"- *{label}*: {desc}" for _, label, desc in options),
            "options": [(value, label) for value, label, _ in options],
            "skippable": True,
        })
    for key, question in FREE_TEXT_ITEMS:
        steps.append({"kind": "text", "key": key, "question": f"**{question}**\n_Type your answer, or `skip` to leave it blank._"})
    steps.append({
        "kind": "choice",
        "key": "consent",
        "question": CONSENT_QUESTION,
        "options": [("yes", "Yes, keep my data"), ("no", "No, delete my data")],
        "skippable": False,
    })
    return steps


def apply_survey_answer(responses: SurveyResponses, step: Dict[str, Any], value: Any) -> None:
    """Record one answer on ``responses`` according to the step definition."""
    key = step["key"]
    if step["kind"] == "text":
        text = (value or "").strip()
        responses.free_text[key] = None if not text or text.lower() == "skip" else text
    elif key == "consent":
        responses.consent = value == "yes"
    elif key in {"time_saved", "tone", "complexity"}:
        setattr(responses, key, value)
    else:
        responses.likert[key] = value
