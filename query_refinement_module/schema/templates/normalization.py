"""Agent A: Research Statement Normalization prompt template."""

NORMALIZATION_TEMPLATE = """
# RESEARCH STATEMENT NORMALIZATION

## Role
Produce a normalized research statement that integrates the original query with all clarified dimensions. Return the dimension values exactly as given.

Return exactly one valid JSON object and no other text.

## Output Schema

{
  "research_statement": "",
  "dimensions_specifications": {}
}

---

## research_statement

One sentence integrating the original query with all non-null dimensions.

Rules:
1. Dimension values override conflicting content in the original query.
2. Expand abbreviations on first use when the expansion is certain; retain both forms as `full form (ABBR)`.
3. Correct obvious typos.
4. Remove filler language: "I think", "I want to study", "maybe", "um", "well", "perhaps".
5. Preserve sentence mode: a question stays a question; a statement stays a statement.
6. Preserve negations verbatim: "without X", "excluding Y", "not involving Z", "outside Z". Do not strip negated modifiers.
7. Preserve compound multi-word concepts intact; do not split them into components.
8. If all dimensions are [SKIPPED], normalize the original query alone.
9. Do not add any content not present in the inputs.

## dimensions_specifications

Include every dimension key from the input exactly once, in input order.
Map [SKIPPED] values to null. Use the provided value string otherwise.

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Use valid JSON: double quotes, escaped internal quotes, no trailing commas.
- dimensions_specifications must include every input dimension key.
""".strip()

__all__ = ["NORMALIZATION_TEMPLATE"]
