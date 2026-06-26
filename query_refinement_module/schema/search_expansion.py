"""Agent D — block-aware search expansion with deterministic Level 1 construction."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .response import CombinedBlock, SearchExpansionInput


# ---------------------------------------------------------------------------
# Boolean query builders
# ---------------------------------------------------------------------------

GEOGRAPHY_ROLES = {"geography", "geography_or_setting"}
SETTING_ROLES = {"setting_or_context"}
POPULATION_ROLES = {"population_or_entity"}


def _quote_if_phrase(term: str) -> str:
    return f'"{term}"' if " " in term.strip() else term.strip()


def _or_group(terms: List[str]) -> str:
    """Build OR-joined parenthesised group from a list of terms."""
    quoted = [_quote_if_phrase(t) for t in terms if t and t.strip()]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return f"({quoted[0]})"
    return "(" + " OR ".join(quoted) + ")"


def _enrich_block_terms(block: CombinedBlock, concept_graph: Dict[str, Any]) -> List[str]:
    """Merge block.free_text with domain_terms from any concept whose query_role matches."""
    terms: List[str] = list(block.free_text)
    for entry in concept_graph.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("query_role", "") == block.role:
            domain_terms = entry.get("domain_terms") or []
            for t in domain_terms:
                if t and t not in terms:
                    terms.append(t)
    return terms


def _merge_cv(
    target: Dict[str, List[str]],
    block: CombinedBlock,
) -> None:
    """Merge block.controlled_vocabulary into target dict in-place, deduplicating terms."""
    for vocab_name, vocab_terms in block.controlled_vocabulary.items():
        if vocab_name not in target:
            target[vocab_name] = []
        for t in vocab_terms:
            if t and t not in target[vocab_name]:
                target[vocab_name].append(t)


def build_level1_query(
    blocks: List[CombinedBlock],
    concept_graph: Dict[str, Any],
) -> Tuple[str, Dict[str, List[str]]]:
    """Deterministically build Level 1 boolean query + controlled vocabulary.

    Returns (search_query, controlled_vocabulary) where:
    - search_query: generic boolean (free-text + domain_terms, no field tags)
    - controlled_vocabulary: merged MeSH/vocab terms from all blocks, for database-specific connectors
    """
    parts: List[str] = []
    cv: Dict[str, List[str]] = {}
    for block in blocks:
        terms = _enrich_block_terms(block, concept_graph)
        group = _or_group(terms)
        if group:
            parts.append(group)
        _merge_cv(cv, block)
    return " AND ".join(parts), cv


def build_leveln_query(
    blocks: List[CombinedBlock],
    concept_graph: Dict[str, Any],
    broadened_role: str,
    replacement_terms: List[str],
) -> Tuple[str, Dict[str, List[str]]]:
    """Build Level N query by substituting or removing the block for broadened_role.

    replacement_terms=[] → remove the block entirely (geography Level 3 only).
    replacement_terms=[...] → replace with the given terms (Level 2, or setting Level 2).
    All other blocks are built identically to Level 1.

    The broadened block's controlled_vocabulary is always excluded: controlled-vocabulary
    terms for geography or setting are source-specific and must not carry over to
    broadened levels where the constraint has been relaxed.
    """
    parts: List[str] = []
    cv: Dict[str, List[str]] = {}
    for block in blocks:
        if block.role == broadened_role:
            if replacement_terms:
                group = _or_group(replacement_terms)
                if group:
                    parts.append(group)
            # Broadened block CV excluded at all relaxed levels
        else:
            terms = _enrich_block_terms(block, concept_graph)
            group = _or_group(terms)
            if group:
                parts.append(group)
            _merge_cv(cv, block)
    return " AND ".join(parts), cv


def build_level0_query(
    blocks: List[CombinedBlock],
) -> Tuple[str, Dict[str, List[str]]]:
    """Build Level 0 boolean query — anchor_blocks free_text as-is, no domain_terms enrichment.

    Used as Level 0 search_query fallback when keyword_structured is not provided.
    """
    parts: List[str] = []
    cv: Dict[str, List[str]] = {}
    for block in blocks:
        group = _or_group(block.free_text)
        if group:
            parts.append(group)
        _merge_cv(cv, block)
    return " AND ".join(parts), cv


def _is_keyword_query_term(term: str) -> bool:
    normalized = term.strip()
    if not normalized:
        return False
    if "*" in normalized:
        return False
    return True


def build_keyword_statement(blocks: List[CombinedBlock], max_terms_per_block: int = 3) -> str:
    """Build compact keyword statement from blocks — top free_text terms joined by spaces.

    Mirrors Agent B's keyword_statement style: key concepts, no boolean operators.
    Used for Levels 1-3 where Agent B's keyword_statement is unavailable.
    """
    terms: List[str] = []
    for block in blocks:
        selected: List[str] = []
        for term in block.free_text:
            cleaned = term.strip()
            if not _is_keyword_query_term(cleaned):
                continue
            selected.append(cleaned)
            if len(selected) >= max_terms_per_block:
                break
        terms.extend(selected)
    return " ".join(terms)


def build_level1_blocks(
    blocks: List[CombinedBlock],
    concept_graph: Dict[str, Any],
) -> List[CombinedBlock]:
    """Build Level 1 CombinedBlocks — anchor_blocks enriched with domain_terms from concept_graph.

    These mirror what build_level1_query puts in search_query, but as structured blocks
    that connectors can use for source-specific query construction (e.g. PubMed field tags).
    """
    result: List[CombinedBlock] = []
    for block in blocks:
        result.append(CombinedBlock(
            role=block.role,
            free_text=_enrich_block_terms(block, concept_graph),
            controlled_vocabulary=dict(block.controlled_vocabulary),
        ))
    return result


def build_leveln_blocks(
    blocks: List[CombinedBlock],
    concept_graph: Dict[str, Any],
    broadened_role: str,
    replacement_terms: List[str],
    replacement_cv: Optional[Dict[str, List[str]]] = None,
) -> List[CombinedBlock]:
    """Build Level N CombinedBlocks by substituting or removing the block for broadened_role.

    replacement_terms=[] → remove the block entirely (geography Level 3).
    replacement_terms=[...] → replace with new terms; replacement_cv provides optional CV
        (e.g. MeSH terms for a broadened setting block).
    All other blocks are enriched identically to Level 1.
    """
    result: List[CombinedBlock] = []
    for block in blocks:
        if block.role == broadened_role:
            if replacement_terms:
                result.append(CombinedBlock(
                    role=block.role,
                    free_text=list(replacement_terms),
                    controlled_vocabulary=dict(replacement_cv or {}),
                ))
            # If no replacement_terms: block removed (Level 3 geography) — not appended
        else:
            result.append(CombinedBlock(
                role=block.role,
                free_text=_enrich_block_terms(block, concept_graph),
                controlled_vocabulary=dict(block.controlled_vocabulary),
            ))
    return result


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _block_summary(blocks: List[CombinedBlock]) -> str:
    """Compact JSON summary of blocks for the LLM prompt."""
    summary = []
    for b in blocks:
        entry: dict = {"role": b.role, "terms": b.free_text[:8]}
        if b.controlled_vocabulary:
            entry["controlled_vocabulary"] = {
                k: v[:4] for k, v in b.controlled_vocabulary.items() if v
            }
        summary.append(entry)
    return json.dumps(summary, ensure_ascii=False, indent=2)


class SearchExpansionPromptBuilder:
    """Build system and user prompts for Agent D expansion call."""

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.search_expansion import SEARCH_EXPANSION_TEMPLATE
        return SEARCH_EXPANSION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        search_input: SearchExpansionInput,
        level1_query: str,
        broadened_role: Optional[str] = None,
    ) -> str:
        geo_blocks = [b for b in search_input.anchor_blocks if b.role in GEOGRAPHY_ROLES]
        has_geography = bool(geo_blocks)

        parts = [f"## Anchor\n\n{search_input.clarified_query}"]
        parts.append(
            f"## Block structure (Agent C output)\n\n"
            f"{_block_summary(search_input.anchor_blocks)}"
        )
        parts.append(f"## Level 1 query (already built — do not regenerate)\n\n{level1_query}")

        if has_geography:
            geo_terms = [t for b in geo_blocks for t in b.free_text]
            parts.append(
                f"## Geography block\n\n"
                f"Role: {geo_blocks[0].role}\n"
                f"Terms: {', '.join(geo_terms)}\n\n"
                f"Generate Level 2 (contextual analogy or geographic superset) and "
                f"Level 3 (remove geography block entirely — Cochrane-sensitive search)."
            )
        else:
            target_blocks = [
                b for b in search_input.anchor_blocks
                if broadened_role and b.role == broadened_role
            ]
            if target_blocks:
                block_terms = [t for b in target_blocks for t in b.free_text]
                parts.append(
                    f"## Setting/context block (no geography detected)\n\n"
                    f"Role: {target_blocks[0].role}\n"
                    f"Terms: {', '.join(block_terms)}\n\n"
                    f"No geographic restriction is present — Level 1 is already geographically unrestricted.\n"
                    f"Generate Level 2 only: broaden this block with adjacent context types "
                    f"(e.g. 'hospitals' → 'hospitals OR clinics OR outpatient care settings'). "
                    f"Do NOT remove this block — it defines the research scope.\n"
                    f"Set geography_broadening_strategy to 'none'. "
                    f"Output only Level 2 in the levels array."
                )

        return "\n\n".join(parts)


__all__ = [
    "build_level0_query",
    "build_level1_query",
    "build_level1_blocks",
    "build_leveln_query",
    "build_leveln_blocks",
    "build_keyword_statement",
    "SearchExpansionPromptBuilder",
    "GEOGRAPHY_ROLES",
    "SETTING_ROLES",
    "POPULATION_ROLES",
]
