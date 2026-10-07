"""Deterministic, domain-agnostic checks on the anchor Boolean search.

Agent C writes the Boolean query (``keyword.structured``) and its block
decomposition (``keyword.combined_blocks``). Each AND-block narrows the
result set, so any block that does not encode a real restriction from the
user's information need costs recall. This module detects such blocks and the
structural problems that make a query unusable, and can repair the query by
dropping offending blocks. Every repair is reported so it can be traced.

Checks:
- syntax: balanced parentheses, no empty groups, no dangling operators, no double quotes
- alignment: top-level AND groups correspond one-to-one with combined_blocks
- redundancy: a block whose every term restates a term of another block
  ("patients with X" next to a block for "X") adds no information but narrows
  the search to the restated phrasing
- grounding: a block sharing no content word with what the user actually
  provided (original question + accepted dimension values) is an LLM invention
- leakage: broadening (domain_terms) or colloquial terms from the concept graph
  appearing in the anchor query, which the pipeline reserves for expansion
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Function words and generic research vocabulary carry no topical signal
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "how", "in", "into", "is", "it", "its", "not", "of", "on", "or", "over", "than", "that",
    "the", "their", "them", "these", "this", "those", "to", "under", "versus", "vs", "was",
    "were", "what", "when", "which", "who", "whom", "why", "with", "within", "without",
    "all", "any", "each", "every", "other", "others", "such", "no", "none", "only", "also",
    "people", "person", "persons", "individual", "individuals", "group", "groups",
    "study", "studies", "research", "evidence", "effect", "effects", "effective",
    "effectiveness", "impact", "impacts", "outcome", "outcomes", "use", "using", "based",
    "related", "type", "types", "level", "levels", "patient", "patients", "population",
    "populations", "participant", "participants", "restriction", "restrictions",
    "specific", "specified", "general", "various", "including", "include", "includes",
    "sufferers", "subjects", "cases", "case", "those", "living", "diagnosed", "having",
    "help", "helps", "improve", "improves", "improving", "reduce", "reduces", "reducing",
    "work", "works", "common", "after", "before", "during", "between", "among", "across",
}
_STEM_LENGTH = 5
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _content_stems(text: str) -> Set[str]:
    """Lower-cased content-word stems (crude prefix stemming, language-light)."""
    stems = set()
    for word in _WORD_RE.findall((text or "").lower().replace("*", "")):
        word = word.strip("-")
        if len(word) < 2 or word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]  # crude plural folding: DOACs -> doac, camps -> camp
        stems.add(word[:_STEM_LENGTH])
    return stems


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").lower().replace("*", "").replace('"', "")).strip()


def split_top_level(structured: str, operator: str = "AND") -> List[str]:
    """Split a Boolean string on ``operator`` at parenthesis depth 0."""
    parts, depth, start = [], 0, 0
    text = structured or ""
    token = f" {operator} "
    i = 0
    while i < len(text):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith(token, i):
            parts.append(text[start:i].strip())
            i += len(token)
            start = i
            continue
        i += 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def check_syntax(structured: str) -> List[str]:
    """Return syntax problems; an empty list means the query is well-formed."""
    problems = []
    text = structured or ""
    if not text.strip():
        return ["empty query"]
    depth = 0
    for char in text:
        depth += char == "("
        depth -= char == ")"
        if depth < 0:
            problems.append("unbalanced parentheses")
            break
    if depth > 0:
        problems.append("unbalanced parentheses")
    if re.search(r"\(\s*\)", text):
        problems.append("empty group")
    if re.search(r"\b(AND|OR|NOT)\s*(\)|$)", text) or re.search(r"(^|\()\s*(AND|OR)\b", text):
        problems.append("dangling operator")
    if re.search(r"\b(AND|OR)\s+(AND|OR)\b", text):
        problems.append("consecutive operators")
    if '"' in text:
        problems.append("double quotes in query")
    return problems


def _block_terms(block: Dict[str, Any]) -> List[str]:
    return [_normalize_term(term) for term in (block.get("free_text") or []) if _normalize_term(term)]


def _restates(term: str, other_terms: Iterable[str]) -> bool:
    """True when ``term`` is another block's term plus only generic words.

    "patients with copd" restates "copd"; "older adults" does not restate
    "adults" because "older" is a real restriction.
    """
    padded = f" {term} "
    for other in other_terms:
        if not other or f" {other} " not in padded:
            continue
        residual = padded.replace(f" {other} ", " ", 1)
        if not _content_stems(residual):
            return True
    return False


def find_redundant_blocks(blocks: Sequence[Dict[str, Any]]) -> List[int]:
    """Indices of blocks whose every term embeds a term of some single other block."""
    terms = [_block_terms(block) for block in blocks]
    redundant: List[int] = []
    for i, own in enumerate(terms):
        if not own:
            continue
        for j, other in enumerate(terms):
            if i == j or j in redundant or not other:
                continue
            if all(_restates(term, other) for term in own):
                redundant.append(i)
                break
    return redundant


def find_ungrounded_blocks(blocks: Sequence[Dict[str, Any]], source_text: str) -> List[int]:
    """Indices of blocks sharing no content word with the user-provided text."""
    source = _content_stems(source_text)
    if not source:
        return []
    ungrounded = []
    for index, block in enumerate(blocks):
        block_stems = set()
        for term in _block_terms(block):
            block_stems |= _content_stems(term)
        if block_stems and not (block_stems & source):
            ungrounded.append(index)
    return ungrounded


def find_leaked_terms(structured: str, concept_graph: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Broadening/colloquial terms that should not be in the anchor query."""
    if not concept_graph:
        return {}
    query_terms = {
        _normalize_term(term)
        for group in split_top_level(structured)
        for term in split_top_level(group.strip("() "), "OR")
    }
    leaks: Dict[str, List[str]] = {}
    for field in ("domain_terms", "colloquial"):
        reserved = set()
        protected = set()
        for entry in concept_graph.values():
            entry = entry if isinstance(entry, dict) else getattr(entry, "model_dump", lambda: {})()
            reserved |= {_normalize_term(term) for term in entry.get(field) or []}
            for allowed in ("true_synonyms", "abbreviations", "spelling_variants", "lexical_variants"):
                protected |= {_normalize_term(term) for term in entry.get(allowed) or []}
        protected |= {_normalize_term(key) for key in concept_graph}
        found = sorted((query_terms & reserved) - protected)
        if found:
            leaks[field] = found
    return leaks


def assess_search(
    structured: str,
    blocks: Sequence[Dict[str, Any]],
    *,
    source_text: str,
    concept_graph: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute search-readiness indicators for one anchor query."""
    groups = split_top_level(structured)
    terms_per_block = [len(block.get("free_text") or []) for block in blocks]
    report = {
        "block_count": len(blocks),
        "and_group_count": len(groups),
        "aligned": len(groups) == len(blocks),
        "syntax_problems": check_syntax(structured),
        "redundant_blocks": find_redundant_blocks(blocks),
        "ungrounded_blocks": find_ungrounded_blocks(blocks, source_text),
        "leaked_terms": find_leaked_terms(structured, concept_graph),
        "terms_per_block": terms_per_block,
        "empty_blocks": [i for i, count in enumerate(terms_per_block) if count == 0],
        "block_roles": [block.get("role") for block in blocks],
    }
    report["issue_count"] = (
        len(report["syntax_problems"])
        + (0 if report["aligned"] else 1)
        + len(report["redundant_blocks"])
        + len(report["ungrounded_blocks"])
        + sum(len(v) for v in report["leaked_terms"].values())
        + len(report["empty_blocks"])
    )
    report["search_ready"] = report["issue_count"] == 0
    return report


def repair_search(
    structured: str,
    blocks: Sequence[Dict[str, Any]],
    *,
    source_text: str,
    min_blocks: int = 2,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Drop redundant and ungrounded blocks when the query structure allows it safely.

    Returns ``(structured, blocks, actions)``. The query is left untouched when
    its AND-groups do not align with ``blocks`` or when dropping would leave
    fewer than ``min_blocks`` blocks.
    """
    groups = split_top_level(structured)
    blocks = list(blocks)
    if len(groups) != len(blocks) or check_syntax(structured):
        return structured, blocks, []

    actions: List[Dict[str, Any]] = []
    candidates: List[Tuple[int, str]] = [(i, "redundant") for i in find_redundant_blocks(blocks)]
    seen = {i for i, _ in candidates}
    candidates += [(i, "ungrounded") for i in find_ungrounded_blocks(blocks, source_text) if i not in seen]

    drop: Set[int] = set()
    for index, reason in candidates:
        if len(blocks) - len(drop) - 1 < min_blocks:
            break
        drop.add(index)
        actions.append({
            "action": "drop_block",
            "reason": reason,
            "role": blocks[index].get("role"),
            "terms": list(blocks[index].get("free_text") or []),
        })

    if not drop:
        return structured, blocks, []
    kept_groups = [group for i, group in enumerate(groups) if i not in drop]
    kept_blocks = [block for i, block in enumerate(blocks) if i not in drop]
    return " AND ".join(kept_groups), kept_blocks, actions


def user_source_text(original_query: str, dimension_values: Dict[str, Any]) -> str:
    """Text the user actually provided, for grounding checks."""
    parts = [original_query or ""]
    parts += [str(value) for value in (dimension_values or {}).values() if value not in (None, "", "[SKIPPED]")]
    return "\n".join(parts)


__all__ = [
    "assess_search",
    "check_syntax",
    "find_leaked_terms",
    "find_redundant_blocks",
    "find_ungrounded_blocks",
    "repair_search",
    "split_top_level",
    "user_source_text",
]
