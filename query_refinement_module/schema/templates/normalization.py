"""Agent A: Research Statement Normalization prompt template."""

NORMALIZATION_TEMPLATE = """
# USER'S INPUT NORMALIZATION

## Role
Produce a normalized statement that integrates the original input with all clarified dimensions. Return the dimension values exactly as given.

Return exactly one valid JSON object and no other text.

## Output Schema

{
  "clarified_query": "",
  "dimensions_specifications": {}
}

---

## clarified_query

One sentence integrating the original user's input with all non-null dimensions.

Rules:
1. Each non-null dimension value must appear in full in the normalized statement. Include every detail verbatim; do not summarize, compress, or omit any part of a dimension value. Exception: Rule 2 below overrides this when dimensions conflict.
2. Later dimensions take strict precedence over earlier ones. When two dimensions contain conflicting information for the same attribute (e.g., age range, geography, population type), use ONLY the later dimension's value for that attribute and drop the conflicting part from the earlier dimension entirely — even if Rule 1 would otherwise require it. Do not include both conflicting values.
3. Dimension values override conflicting content in the original input.
4. Expand abbreviations on first use when the expansion is certain; retain both forms as `full form (ABBR)`.
5. Correct obvious typos.
6. Remove filler language: "I think", "I want to study", "maybe", "um", "well", "perhaps".
7. Preserve sentence mode: a question stays a question; a statement stays a statement.
8. Preserve negations verbatim: "without X", "excluding Y", "not involving Z", "outside Z". Do not strip negated modifiers.
9. Preserve compound multi-word concepts intact; do not split them into components.
10. If all dimensions are [SKIPPED], normalize the original input alone.
11. Do not add any content not present in the inputs.

## dimensions_specifications

Include every dimension key from the input exactly once, in input order.
Map [SKIPPED] values to null. Use the provided value string otherwise.

---

## Example — Medicine

Input:

## Original Input:

"I am interested in recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery"

---

## Clarified Dimensions

**Population** (Patient group): Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)
**Intervention** (What is being tested): Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings
**Comparison** (Control or comparator): Within and across classes (comparing interventions both within the same class and between different classes)
**Outcomes** (Primary endpoints): [SKIPPED]

Output:

{
  "clarified_query": "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes.",
  "dimensions_specifications": {
    "Population": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
    "Intervention": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
    "Comparison": "Within and across classes (comparing interventions both within the same class and between different classes)",
    "Outcomes": null
  }
}

Note what changed: filler phrase "I am interested in" was removed (Rule 6); "recent studies about" was retained because it is meaningful scope content, not filler; all four dimension keys appear exactly once; Outcomes maps to null because its value was [SKIPPED].

---

## Example — Conflict resolution (Rule 2)

Input:

## Original Input:

"What is the effect of resistance training on muscle strength in older patients?"

---

## Clarified Dimensions

**Population** (Who the study targets): older adults aged 65 and above with no prior resistance training
**Intervention** (What is being tested): progressive resistance training (PRT) programmes, 3 sessions per week for 12 weeks
**Context / setting** (Where the study takes place): community-dwelling adults aged 55 and above in outpatient rehabilitation centres

Output:

{
  "clarified_query": "What is the effect of progressive resistance training (PRT) programmes, 3 sessions per week for 12 weeks, on muscle strength in community-dwelling adults aged 55 and above with no prior resistance training in outpatient rehabilitation centres?",
  "dimensions_specifications": {
    "Population": "older adults aged 65 and above with no prior resistance training",
    "Intervention": "progressive resistance training (PRT) programmes, 3 sessions per week for 12 weeks",
    "Context / setting": "community-dwelling adults aged 55 and above in outpatient rehabilitation centres"
  }
}

Note what changed: Population said "aged 65 and above" but Context / setting (later) said "aged 55 and above" — Rule 2 applies: "aged 65 and above" is dropped from the normalized statement and "aged 55 and above" is used instead. The non-conflicting part of Population ("with no prior resistance training") is retained because it does not conflict with any later dimension.

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Use valid JSON: double quotes, escaped internal quotes, no trailing commas.
- dimensions_specifications must include every input dimension key.
""".strip()

__all__ = ["NORMALIZATION_TEMPLATE"]
