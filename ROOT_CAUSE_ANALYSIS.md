# Root Cause Analysis: Empty followup_question Issue

## The Problem

After submitting an answer, the backend returns `next_prompt.question` as empty/null, causing the frontend to show nothing.

## Root Cause

The `mph_dissertation.yaml` framework **does not define a `response_format` schema**. This causes:

1. LLM returns free-text responses (not structured JSON)
2. `_get_llm_response_with_validation()` returns `parsed_payload = None` (line 1864)
3. `followup_question = parsed_payload.get("followup_question")` fails because `parsed_payload` is None
4. `followup_question` remains None/empty
5. `step.refinement_question` gets set to empty if the condition passes (line 981)
6. Frontend receives empty question and renders nothing

## Code Flow

```python
# core.py line ~940
if parsed_payload:  # This is None for mph_dissertation!
    followup_question = parsed_payload.get("followup_question")  # Never executes
    
# followup_question is None here

# line ~981
if followup_question:  # Fails, so refinement_question not updated
    step.refinement_question = followup_question
```

## Why mph_dissertation Lacks response_format

Looking at the YAML, mph_dissertation is designed for **conversational, adaptive refinement**:
- System prompts emphasize natural dialogue
- Prompts say "engage conversationally, not like a form"
- Expected to generate contextual follow-up questions based on student responses

This is fundamentally different from frameworks with structured schemas (like PICO) which have fixed fields to extract.

## The Design Conflict

**Two paradigms in the codebase:**

### 1. Structured Schema Mode (PICO frameworks)
```yaml
response_format:
  type: "json_schema"
  json_schema:
    schema:
      properties:
        followup_question:
          type: string
        is_complete:
          type: boolean
```
- LLM returns JSON
- System extracts `followup_question` from parsed JSON
- Works perfectly

### 2. Conversational Mode (mph_dissertation)
- No response_format
- LLM returns natural text
- System treats entire response as the question
- **But code assumes parsed_payload exists!**

## The Actual Issue

The `run_followup_until_clear()` function was written assuming all aspects have `response_format`. The mph_dissertation framework breaks this assumption.

## Robust Solution

We need to handle BOTH modes properly:

```python
def run_followup_until_clear(self, session, aspect_id=None, max_rounds=None):
    step = self._get_target_step(session, aspect_id)
    rounds = 0
    max_followups = max_rounds if max_rounds is not None else step.refinement_aspect.max_follow_ups

    if step.is_complete:
        final_value = self._extract_final_value(step)
        return self._build_followup_result(step, final_value, rounds)

    parsed_payload = None
    final_value = None
    followup_question = None
    reasoning = None
    response_text = None
    error_message = None
    is_error = False

    while not step.is_complete and rounds < max_followups:
        dependency_context = session.get_dependency_context(step.refinement_aspect.id)
        system_prompt, user_prompt = step.get_prompts(
            query=session.original_query,
            dependency_context=dependency_context
        )
        
        response_text, parsed_payload, is_error, error_message = self._get_llm_response_with_validation(
            aspect=step.refinement_aspect,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        
        if is_error:
            step.add_follow_up(
                question=step.refinement_question or step.refinement_aspect.aspect_name,
                response=f"[Validation error: {error_message}]"
            )
            step.is_complete = True
            break
        
        # CRITICAL: Handle both structured and conversational modes
        if parsed_payload:
            # Structured mode: Extract from JSON
            final_value = parsed_payload.get("final_value")
            followup_question = parsed_payload.get("followup_question")
            reasoning = parsed_payload.get("reasoning")
            is_complete = parsed_payload.get("is_complete", False)
        else:
            # Conversational mode: Use raw LLM response as the question
            followup_question = response_text.strip() if response_text else None
            is_complete = False  # Cannot determine completion from free text
            
            # For conversational mode, we rely on max_followups to end the loop
            # or explicit completion keywords if implemented
        
        # Store the follow-up
        step.add_follow_up(
            question=followup_question or step.refinement_question or step.refinement_aspect.aspect_name,
            response=response_text
        )
        
        rounds += 1
        
        # Check max rounds
        if rounds == max_followups:
            if parsed_payload and parsed_payload.get("is_complete", False):
                step.is_complete = True
                step.needs_refinement_rationale = reasoning
                if final_value is not None:
                    step.initial_summary = final_value
                else:
                    step.initial_summary = response_text
            else:
                # For conversational mode, complete after max rounds
                step.is_complete = True
                step.initial_summary = response_text
            break
        
        # Check completion (structured mode only)
        if parsed_payload and parsed_payload.get("is_complete", False):
            step.is_complete = True
            step.needs_refinement_rationale = reasoning
            if final_value is not None:
                step.initial_summary = final_value
            else:
                step.initial_summary = response_text
            break
        
        # Update refinement_question for next round
        # CRITICAL: Only update if we have a valid follow-up question
        if followup_question and followup_question.strip():
            step.refinement_question = followup_question
        # If no followup_question, keep the existing one
    
    final_value = self._extract_final_value(step)
    return self._build_followup_result(step, final_value, rounds)
```

## Key Changes

### 1. Detect Mode
```python
if parsed_payload:
    # Structured mode
    followup_question = parsed_payload.get("followup_question")
else:
    # Conversational mode  
    followup_question = response_text.strip()
```

### 2. Handle Completion Logic
- **Structured mode**: Use `is_complete` flag from JSON
- **Conversational mode**: Complete after `max_followups` rounds

### 3. Safe Update
```python
if followup_question and followup_question.strip():
    step.refinement_question = followup_question
# else: keep existing question
```

## Additional Improvements

### 1. Add Completion Detection for Conversational Mode

Optionally add keyword detection:
```python
# For conversational mode without schema
if not parsed_payload and response_text:
    # Check for completion keywords
    completion_keywords = [
        "that's clear now",
        "no further questions",
        "we have everything we need",
        "ready to move on"
    ]
    if any(keyword in response_text.lower() for keyword in completion_keywords):
        is_complete = True
```

### 2. Log Mode Detection
```python
logger.debug(
    "Aspect %s running in %s mode (response_format: %s)",
    aspect.id,
    "structured" if parsed_payload else "conversational",
    "defined" if aspect.response_format else "none"
)
```

### 3. Frontend Robustness
Already done:
- Check `currentQuestion && currentQuestion.question`
- Add console logging
- Handle null gracefully

## Testing Strategy

### 1. Test Structured Mode (PICO)
- Use framework with response_format
- Verify `followup_question` extracted from JSON
- Verify `is_complete` flag works

### 2. Test Conversational Mode (mph_dissertation)
- Use framework without response_format  
- Verify response_text used as question
- Verify max_followups terminates loop
- Verify question is never empty

### 3. Test Edge Cases
- Empty LLM response
- Malformed JSON in structured mode
- Very long responses in conversational mode
- Network errors

## Long-term Solution

### Option A: Add response_format to mph_dissertation

```yaml
response_format:
  type: json_schema
  json_schema:
    schema:
      type: object
      properties:
        followup_question:
          type: string
          description: "The next clarifying question to ask the student, or empty if aspect is clear"
        is_clear:
          type: boolean
          description: "True if this aspect is now sufficiently clear"
        assessment:
          type: string
          description: "Brief reasoning about clarity"
      required: [followup_question, is_clear]
```

**Pros:**
- Consistent with other frameworks
- Explicit completion detection
- Structured extraction

**Cons:**
- Less conversational feel
- Constrains LLM creativity
- Requires updating all system_prompts

### Option B: Keep Both Paradigms

Support both modes explicitly:
- Structured for analytical frameworks (PICO)
- Conversational for advisory frameworks (mph_dissertation)

**Pros:**
- Preserves conversational nature
- Flexibility for different use cases

**Cons:**
- More complex code
- Two code paths to maintain

## Recommendation

**Implement Option B** (dual mode support) because:

1. **Preserves Design Intent**: mph_dissertation was intentionally designed for natural conversation
2. **Flexibility**: Supports different framework types
3. **Backward Compatible**: Doesn't break existing frameworks
4. **Robust**: Handles both paradigms cleanly

The fix is straightforward:
```python
followup_question = (
    parsed_payload.get("followup_question") if parsed_payload 
    else response_text.strip() if response_text 
    else None
)
```

This respects the framework's design while ensuring the system never returns empty questions.
