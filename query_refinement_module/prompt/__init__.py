"""
Prompt templates for query refinement system.
"""

from .system_role import GLOBAL_SYSTEM_PROMPT
from .user import EVALUATION_CRITERIA_PROMPT

__all__ = [
    "GLOBAL_SYSTEM_PROMPT",
    "EVALUATION_CRITERIA_PROMPT",
]
