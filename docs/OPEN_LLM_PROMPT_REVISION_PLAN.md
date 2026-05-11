# Open LLM Prompt Revision Plan

This document tracks prompt-compaction changes made specifically for open-weight
models such as Qwen 2.5, while preserving the existing prompt behavior for
private/proprietary models.

## Goal

Reduce prompt length and repeated static instruction load in the open-LLM path
without weakening:

- extraction discipline
- dependency alignment
- completeness handling
- structured JSON output
- prompt-path separation between open and private models

## Separation Contract

The open/private split remains driven by
[query_refinement_module/schema/templates/__init__.py](../query_refinement_module/schema/templates/__init__.py):

- `PROMPT_VARIANT=open_llm` explicitly selects the open prompt branch
- otherwise `LLM_MODEL` inference selects the open branch for markers such as
  `ollama/`, `qwen`, `llama`, `mistral`, `gemma`, and `deepseek`
- the private path continues to use the canonical templates by default

Builder-level behavior must respect the same split rather than inventing a new
provider-classification mechanism.

## Implemented Changes

### 1. Open-only user-context compaction

The open template in
[query_refinement_module/schema/templates/user_context_open_llm.py](../query_refinement_module/schema/templates/user_context_open_llm.py)
was shortened by:

- collapsing repeated tone/complexity reminders
- shortening the rendered profile section
- reducing the APPLICATION section to the nonredundant guidance that user
  context only shapes phrasing, framing, and depth

The private template in
[query_refinement_module/schema/templates/user_context.py](../query_refinement_module/schema/templates/user_context.py)
was intentionally left unchanged.

### 2. Open-only terminal reinforcement compaction

The shared builder in
[query_refinement_module/schema/prompt_builder.py](../query_refinement_module/schema/prompt_builder.py)
now distinguishes between prompt variants when terminal reinforcement fires:

- open-LLM path: reuses a compact style cue
- private path: retains the full rendered user-context reinforcement

This preserves recency support for open models without re-injecting the full
static user-context block late in the message list.

### 3. Measurement support in the open evaluation harness

[scripts/evaluate_open_llm_prompts.py](../scripts/evaluate_open_llm_prompts.py)
now reports prompt-size metrics per case and in the final summary:

- total characters per case
- message count per case
- aggregate total / average / max prompt size across the run

These metrics are intentionally simple and deterministic. They are meant to
track before/after compaction deltas, not tokenizer-exact billing estimates.

## Validation Requirements

Any further open-only prompt compaction should pass all of the following:

1. Template-selection tests in
   [tests/unit/test_template_variant_selection.py](../tests/unit/test_template_variant_selection.py)
2. Prompt-structure tests in
   [tests/test_message_structure.py](../tests/test_message_structure.py)
3. Focused config/template test slice already used in the repo
4. Python compilation for edited files
5. Runtime validation via
   [scripts/evaluate_open_llm_prompts.py](../scripts/evaluate_open_llm_prompts.py)

## Current Risks to Watch

1. Over-shortening the open user-context template may remove useful style
   anchoring and cause flatter or more brittle questioning behavior.
2. The completed-dimensions reminder in the builder is still shared and still
   adds prompt length. It was kept because it carries runtime content rather
   than only static instruction duplication.
3. Prompt selection still happens at module-import time for the template
   strings. Tests or tooling that change `PROMPT_VARIANT` or `LLM_MODEL` during
   execution must reload the affected modules.

## Next Candidates

If more prompt reduction is needed after measuring the current savings:

1. Trim static examples from the open completed-dimensions block before cutting
   dependency-alignment instructions.
2. Add a dedicated test that compares open vs private terminal reinforcement
   payload size directly.
3. Consider optional token-count measurement in the open eval harness if raw
   character count is not discriminative enough.