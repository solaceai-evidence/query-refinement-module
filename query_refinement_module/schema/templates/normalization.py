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

## Example — Medicine

Input:

**Original Query:** "I am interested in recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery"

**Population** (Patient group): Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)
**Intervention** (What is being tested): Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings
**Comparison** (Control or comparator): Within and across classes (comparing interventions both within the same class and between different classes)
**Outcomes** (Primary endpoints): [SKIPPED]

Output:

{
  "research_statement": "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes.",
  "dimensions_specifications": {
    "Population": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
    "Intervention": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
    "Comparison": "Within and across classes (comparing interventions both within the same class and between different classes)",
    "Outcomes": null
  }
}

Note what changed: filler phrase "I am interested in" was removed (Rule 4); "recent studies about" was retained because it is meaningful scope content, not filler; all four dimension keys appear exactly once; Outcomes maps to null because its value was [SKIPPED].

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Use valid JSON: double quotes, escaped internal quotes, no trailing commas.
- dimensions_specifications must include every input dimension key.
""".strip()

__all__ = ["NORMALIZATION_TEMPLATE"]
