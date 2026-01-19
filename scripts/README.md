# Utility Scripts

## print_framework_prompts.py

Inspect and verify the generated prompts for refinement frameworks.

### Usage

```bash
poetry run python scripts/print_framework_prompts.py <framework_yaml> <framework_name> [options]
```

### Options

- `--query <text>` - Custom query to test (default: 'sample research query')
- `--aspect <id>` - Show only specific aspect by ID
- `--summary` - Show compact summary instead of full prompts
- `--followup` - Also show follow-up mode example with conversation history

### Examples

**View all aspects in summary mode:**
```bash
poetry run python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced --summary
```

**Inspect a specific aspect with custom query:**
```bash
poetry run python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced \
  --aspect population_demographic \
  --query "effects of aspirin on stroke"
```

**See both initial and follow-up mode prompts:**
```bash
poetry run python scripts/print_framework_prompts.py examples/mph_dissertation.yaml mph_dissertation \
  --aspect population \
  --query "childhood obesity interventions" \
  --followup
```

**Check all prompts for a framework:**
```bash
poetry run python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced
```

### What It Shows

1. **System Prompt** - The role/persona the LLM adopts for this aspect
2. **Unified Prompt (Initial)** - Complete prompt as it appears in production:
   - Original query
   - Refinement instructions with examples
   - Dynamically-built output format from BASE_SCHEMA_FIELDS
3. **Unified Prompt (Follow-up)** - With `--followup` flag:
   - Conversation history (Q&A exchanges)
   - Completed dependencies with visual markers
   - Same format as initial but with additional context

### Use Cases

- **Verify prompt changes** - After modifying BASE_SCHEMA_FIELDS or BASE_FIELD_DESCRIPTIONS, check that prompts update correctly
- **Review examples** - Ensure examples from YAML are formatted properly
- **Debug dependencies** - See how dependency context is displayed
- **Test with real queries** - Use `--query` to see how prompts look with actual research questions
- **Quick overview** - Use `--summary` to see configuration of all aspects at once

### Architecture Note

The script uses `RefinementAspect.build_unified_prompt()` which ensures you see the **exact same prompt** that the LLM receives in production. The output format section is built dynamically from `BASE_SCHEMA_FIELDS` and `BASE_FIELD_DESCRIPTIONS` - no hardcoding!
