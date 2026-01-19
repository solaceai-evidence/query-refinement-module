"""
Unified prompt template for refinement analysis.

This module provides a single prompt template used for both initial and
follow-up analysis, with conditional sections based on conversation state.
"""

from typing import List, Dict, Any, Literal, Optional
from ..schema.model import RefinementAspect


UNIFIED_ANALYSIS_PROMPT = """
**Aspect:** {aspect_name}
**Description:** {aspect_description}

---

**Original Input:**
"{original_query}"

{conversation_section}

{dependency_section}

{refinement_instructions}

{examples_section}

---

**OUTPUT (JSON):**

{{
  "is_complete": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "why complete/incomplete (1-2 sentences)",
  "refinement_aspect_value": "clear, specific value (if complete) OR null",
  "next_question": "focused question with inline examples (if incomplete) OR null"
}}

**Rules:**
- `is_complete=true` → `refinement_aspect_value` must be non-null, `next_question` must be null
- `is_complete=false` → `next_question` must be non-null, `refinement_aspect_value` must be null
- `confidence`: 0.9-1.0 (very clear), 0.7-0.89 (clear), 0.5-0.69 (moderate), <0.5 (uncertain)
- `refinement_aspect_value`: Extract verbatim from original input/dependency context, or combine user's answers preserving their exact wording and intended meaning. Do NOT rephrase or reinterpret—capture what the user actually said.
- `next_question`: Include concrete options or examples inline within the question text
"""


def build_conversation_section(
    follow_up_history: List[Dict[str, str]],
    mode: Literal['initial', 'followup']
) -> str:
    """
    Build conversation history section.
    
    Args:
        follow_up_history: List of Q&A exchanges
        mode: 'initial' (no history) or 'followup' (with history)
    
    Returns:
        Formatted conversation section (empty for initial mode)
    """
    if mode == 'initial' or not follow_up_history:
        return ""
    
    lines = ["**Conversation History:**\n"]
    for i, turn in enumerate(follow_up_history, 1):
        question = turn.get('question', '')
        response = turn.get('response', '')
        lines.append(f"Q{i}: {question}")
        lines.append(f"A{i}: {response}\n")
    
    return "\n".join(lines)


def build_dependency_section(
    current_aspect_id: str,
    dependency_context: Dict[str, Dict[str, Any]],
    aspect_dependencies: List[str]
) -> str:
    """
    Build dependency context showing completed aspects.
    
    If current aspect depends on shown aspects, adds a visual marker.
    
    Args:
        current_aspect_id: ID of aspect being analyzed
        dependency_context: Dict mapping aspect IDs to their context
        aspect_dependencies: List of aspect IDs current aspect depends on
    
    Returns:
        Formatted dependency section (empty if no dependencies)
    """
    if not dependency_context:
        return ""
    
    lines = ["**Completed Aspects (for context):**\n"]
    
    has_dependencies = bool(aspect_dependencies)
    
    for dep_id, context in dependency_context.items():
        aspect_name = context.get('name', dep_id)
        aspect_desc = context.get('description', '')
        refined_value = context.get('value', '')
        
        # Mark if current aspect depends on this
        dependency_marker = ""
        if has_dependencies and dep_id in aspect_dependencies:
            dependency_marker = " ⚠️ (this aspect depends on this)"
        
        lines.append(f"**{aspect_name}**{dependency_marker}")
        if aspect_desc:
            lines.append(f"  Description: {aspect_desc}")
        lines.append(f"  Refined Value: {refined_value}\n")
    
    if has_dependencies:
        lines.append("\n⚠️ = Consider these values when analyzing the current aspect\n")
    
    return "\n".join(lines)


def build_refinement_instructions(aspect: RefinementAspect, query: str) -> str:
    """
    Build refinement instructions section.
    
    This uses the aspect's refinement_instructions which contains
    type-specific evaluation criteria and objectives.
    
    Args:
        aspect: RefinementAspect instance
        query: Original query to analyze
    
    Returns:
        Formatted refinement instructions
    """
    # Get the refinement instructions (already formatted in schema)
    instructions = aspect.get_refinement_instructions_prompt(statement=query)
    
    # Add a header
    return f"**Analysis Guidelines:**\n\n{instructions}\n"


def build_examples_section(aspect: RefinementAspect) -> str:
    """
    Build examples section from aspect schema.
    
    Examples come AFTER refinement instructions in the prompt.
    Categories: clear, needs_refinement, partial, vague_ambiguous, other
    
    Args:
        aspect: RefinementAspect instance
    
    Returns:
        Formatted examples section (empty if no examples)
    """
    if not aspect.examples:
        return ""
    
    lines = ["**Examples:**\n"]
    
    # Process each category
    category_map = {
        'clear': 'Clear Examples',
        'needs_refinement': 'Needs Refinement',
        'partial': 'Partial Examples',
        'vague_ambiguous': 'Vague/Ambiguous Examples',
        'other': 'Other Cases'
    }
    
    for category, examples_list in aspect.examples.items():
        if not examples_list:
            continue
        
        category_title = category_map.get(category, category.replace('_', ' ').title())
        lines.append(f"\n{category_title}:")
        
        for ex in examples_list:
            # Get statement or query (statement preferred)
            statement = ex.get('statement') or ex.get('query', '')
            if statement:
                lines.append(f"- Statement: {statement}")
            
            # Add contextual fields (rationale, issue, missing, etc.)
            for key in ['rationale', 'issue', 'missing', 'has', 'example_question', 'note', 'guidance']:
                if key in ex:
                    key_title = key.replace('_', ' ').title()
                    lines.append(f"  {key_title}: {ex[key]}")
            
            lines.append("")  # Blank line between examples
    
    return "\n".join(lines)
