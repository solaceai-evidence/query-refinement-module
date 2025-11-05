# Examples Field Reference Guide

## Quick Field Reference by Category

### `clear` - Complete Specification Examples

**Purpose**: Show what a well-specified query looks like

**Recommended Fields**:
- `query` (required) - The example query
- `explanation` - Why this is clear and complete

**Example**:
```yaml
clear:
  - query: "Does aerobic exercise reduce depression in adults aged 18-65?"
    explanation: "Age range clearly specified (18-65), adult population identified"
```

---

### `needs_refinement` - Missing Information Examples

**Purpose**: Show queries lacking critical information

**Recommended Fields**:
- `query` (required) - The incomplete example query
- `issue` - What's wrong or missing
- `missing` - Specifically what information is absent
- `suggested_question` - Example clarifying question

**Example**:
```yaml
needs_refinement:
  - query: "Does exercise help with depression in adults?"
    issue: "No age range specified - 'adults' is too broad"
    suggested_question: "What age range are you interested in?"
```

---

### `partial` - Partially Specified Examples

**Purpose**: Show queries with some but not all needed information

**Recommended Fields**:
- `query` (required) - The partially complete query
- `has` - What information IS present
- `missing` - What information is still needed
- `suggested_question` - Example question for missing details

**Example**:
```yaml
partial:
  - query: "Effects of diet intervention in women over 40"
    has: "Gender (women) and minimum age (40)"
    missing: "No upper age limit or geographic scope"
    suggested_question: "Is there a specific upper age limit?"
```

---

### `ambiguous` - Vague Specification Examples

**Purpose**: Show queries with unclear or ambiguous terms

**Recommended Fields**:
- `query` (required) - The ambiguous example query
- `issue` - What makes it vague or unclear
- `suggested_question` - Example clarification question

**Example**:
```yaml
ambiguous:
  - query: "Intervention effectiveness in middle-aged adults"
    issue: "'Middle-aged' is ambiguous - could mean 40-65 or other ranges"
    suggested_question: "Can you specify the exact age range?"
```

---

## Type Safety in Python

Each category has a TypedDict type for IDE autocomplete:

```python
from schema.model import (
    ClearExample,           # For 'clear' category
    NeedsRefinementExample, # For 'needs_refinement' category
    PartialExample,         # For 'partial' category
    AmbiguousExample,       # For 'ambiguous' category
    ExamplesDict,           # For the full examples dict
)
```

## Field Summary Table

| Category | Required | Recommended Optional Fields |
|----------|----------|----------------------------|
| `clear` | `query` | `explanation` |
| `needs_refinement` | `query` | `issue`, `missing`, `suggested_question` |
| `partial` | `query` | `has`, `missing`, `suggested_question` |
| `ambiguous` | `query` | `issue`, `suggested_question` |

## Validation Rules

✅ **Valid**:
- Any category can be omitted entirely
- Only `query` field is required per example
- Optional fields can be mixed and matched

❌ **Invalid**:
- Example without `query` field
- Invalid category names (only `clear`, `needs_refinement`, `partial`, `ambiguous` allowed)
- Non-string values for any field
- Category value that's not a list

## Tips

1. **Use contextual fields**: Different categories work better with different optional fields
2. **Be specific**: `issue` and `missing` help the LLM understand what to look for
3. **Show variety**: Include 2-5 examples per category to show different patterns
4. **Real-world examples**: Use actual queries from your domain when possible
