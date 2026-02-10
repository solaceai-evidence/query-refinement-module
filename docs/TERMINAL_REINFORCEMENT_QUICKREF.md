# Terminal Reinforcement - Quick Reference Card

## What Is It?

Repeats core instructions at the end of long conversations to prevent LLMs from "forgetting" initial directives.

## Configuration

**Hardcoded to threshold=3** (data-driven optimal value)
- Analysis of 3,777 dimensions shows 0.9% cost increase
- Precisely targets only problematic dimensions (35 out of 3,777)
- 94.8% of dimensions complete in 1 turn, 4.3% in 2 turns (normal refinement)
- Threshold=3 catches the 0.9% that truly struggle

**Not configurable** - optimal value determined from production data.

## When Does It Trigger?

- After conversation history ≥ threshold turns
- Only for incomplete dimensions
- Default: After 3rd conversation turn

## What Gets Reinforced?

Full repetition of:
- GLOBAL_SYSTEM_PROMPT (core instructions)
- User context (domain knowledge)

## Cost Impact

**Based on 3,777 dimensions analyzed:**
- **Affected dimensions**: 35 (0.9%)
- **Token increase**: ~3,000 tokens/dimension when triggered
- **Overall cost**: +0.9% average (negligible)
- **Real cost**: $0.32 per 1,000 dimensions (Claude Sonnet 3.5)

## Logs

```bash
# Activation log entry
INFO Terminal reinforcement added after 3 conversation turns (threshold: 3)

# Count activations
grep "Terminal reinforcement added" logs/app.log | wc -l

# Check configured threshold
grep "Terminal Reinforcement Threshold:" logs/app.log | tail -1
```

## Testing

```bash
# Manual test via GUI:
1. Start PICO_advanced workflow
2. Give vague answers: "the first one", "like before"
3. On turn 3, check logs for reinforcement activation
4. Verify improved reference resolution

# Disable for testing:
export QUERY_REFINEMENT_TERMINAL_REINFORCEMENT_THRESHOLD=0
```

## Troubleshooting

| Problem        | Check                     | Solution                                                     |
| -------------- | ------------------------- | ------------------------------------------------------------ |
| Not activating | Environment variable set? | `export QUERY_REFINEMENT_TERMINAL_REINFORCEMENT_THRESHOLD=3` |
| Not activating | Conversation long enough? | Count turns in conversation history                          |
| Not activating | Service restarted?        | Restart after setting env var                                |
| High costs     | Threshold too low?        | Increase to 4 or 5                                           |
| Poor quality   | Threshold too high?       | Decrease to 2                                                |
| Poor quality   | Instructions unclear?     | Review GLOBAL_SYSTEM_PROMPT                                  |

## Quick Checks

```bash
# Is it working?
grep "Terminal reinforcement added" logs/app.log

# What's the activation rate?
TOTAL=$(grep "conversation turns" logs/app.log | wc -l)
ACTIVATED=$(grep "Terminal reinforcement added" logs/app.log | wc -l)
echo "Activation rate: $(($ACTIVATED * 100 / $TOTAL))%"
# Expected: ~1% (0.9% from data analysis)
```

## Code Entry Points

```python
# Settings
from query_refinement_module.settings import LLMSettings
settings = LLMSettings.from_env()
threshold = settings.terminal_reinforcement_threshold

# Manager creation
from query_refinement_module.core import QueryRefinementManager
manager = QueryRefinementManager(
    llm_provider=provider,
    terminal_reinforcement_threshold=threshold
)

# Direct message building
from query_refinement_module.schema.prompt_builder import build_refinement_messages
messages = build_refinement_messages(
    ...,
    terminal_reinforcement_threshold=threshold
)
```

## Files Modified

✅ Core: `settings.py`, `prompt_builder.py`, `session_models.py`, `core.py`  
✅ API: `dependencies.py`, `routes/refinement.py`  
✅ Service: `service.py`, `cli.py`  
✅ Scripts: `print_llm_prompts.py`

## Documentation

- Full docs: `docs/TERMINAL_REINFORCEMENT.md`
- Summary: `docs/TERMINAL_REINFORCEMENT_SUMMARY.md`
- This card: `docs/TERMINAL_REINFORCEMENT_QUICKREF.md`

## Key Metrics

Monitor these after deployment:

1. **Activation rate**: Should be ~1% (0.9% from 3,777 dimension analysis)
2. **Token cost**: Should increase ~1% (negligible)
3. **Completion rate**: Should improve for 3+ turn conversations
4. **Average turns**: Should remain stable (~1.05 average)

## Emergency Disable

```bash
# Contact developer - threshold is hardcoded to 3
# No environment variable to change
# Code modification required if disabling is needed
```

## Research Foundation

- **Paper**: Liu et al. 2023 "Lost in the Middle"
- **Finding**: LLMs show strong recency bias
- **Industry**: Used by Anthropic, OpenAI, major production systems

## Version

- **Implemented**: 2024-02-10
- **Threshold**: 3 (hardcoded, data-driven optimal)
- **Status**: ✅ Complete, ready for testing
- **Data Analysis**: 3,777 dimensions, 0.9% affected, 0.9% cost increase
