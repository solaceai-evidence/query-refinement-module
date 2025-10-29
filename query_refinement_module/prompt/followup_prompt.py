UNIVERSAL_FOLLOWUP_PROMPT = """

**Context:**
You are evaluating whether the user's latest answer provides clear, actionable information for aspect {aspect_name} ({aspect_description}), or if a follow-up question is needed.

Original Query: "{original_query}"

**Conversation History:**
{conversation_history}

**Latest User Answer:** "{latest_answer}"
---

**Your Task:**

Evaluate if the user's latest answer provides clear, actionable information for {aspect_name}, or if a follow-up question is needed.

**Evaluation Criteria:**

1. **SUFFICIENT** - Answer is ready to use if:
   ✓ Specific and unambiguous (e.g., "2020-2023", not "recent")
   ✓ Actionable for search (can be directly integrated into query)
   ✓ No conflicting or contradictory information
   ✓ Doesn't introduce new ambiguities

2. **NEEDS FOLLOW-UP** - Ask follow-up if:
   ✗ Answer is vague or imprecise (e.g., "recent", "a few", "some")
   ✗ Answer is too broad and could be narrowed (e.g., "Africa" → which part?)
   ✗ Answer conflicts with query context
   ✗ Answer partially addresses the Aspect but leaves gaps
   ✗ Answer uses ambiguous terms that need clarification

3. **CANNOT IMPROVE** - Accept answer if:
   • User has provided their best attempt and further questions won't help
   • We've already asked follow-ups and aren't getting more specificity
   • The vagueness reflects genuine uncertainty (which is valid)

**Decision Guidelines:**

- Be practical: Don't pursue perfect precision if answer is "good enough"
- Respect user effort: If they've tried to be specific, accept it
- Stay focused: Follow-up should only address {aspect_name}, not introduce new aspects
- Be helpful: If you ask a follow-up, make it easy to answer with concrete options
- Know when to stop: After 2-3 exchanges, accept what you have

**Examples:**

Example 1 - SUFFICIENT:
Aspect: Time Period
Latest Answer: "2020-2023"
→ {{"is_complete": true, "final_value": "2020-2023", "reasoning": "Specific date range provided"}}

Example 2 - NEEDS FOLLOW-UP (vague):
Aspect: Time Period
Latest Answer: "recent studies"
→ {{"is_complete": false, "reasoning": "'Recent' is ambiguous", 
    "followup_question": "How recent? For example: past year, past 2-3 years, or past 5 years?"}}

Example 3 - NEEDS FOLLOW-UP (too broad):
Aspect: Geographic Focus
Latest Answer: "Africa"
→ {{"is_complete": false, "reasoning": "Africa is broad, could be narrowed",
    "followup_question": "Would you like to focus on a specific region (e.g., Sub-Saharan Africa, North Africa, West Africa) or the entire continent?"}}

Example 4 - NEEDS FOLLOW-UP (conflict):
Original Query: "COVID-19 vaccine studies"
Aspect: Time Period
Latest Answer: "past 10 years"
→ {{"is_complete": false, "reasoning": "Timeframe conflicts with topic (COVID-19 vaccines emerged in 2020)",
    "followup_question": "COVID-19 vaccines were developed in 2020. Did you mean 2020-present, or are you interested in earlier coronavirus vaccine research?"}}

Example 5 - SUFFICIENT (context makes it clear):
Original Query: "machine learning for protein folding"
Aspect: Research Field
Latest Answer: "computational biology"
→ {{"is_complete": true, "final_value": "computational biology", "reasoning": "Clear field specification that matches query context"}}

Example 6 - NEEDS FOLLOW-UP (partial answer):
Aspect: Research Field
Latest Answer: "interdisciplinary"
→ {{"is_complete": false, "reasoning": "Interdisciplinary is valid but vague",
    "followup_question": "Which fields specifically? For example: computer science + biology, social science + public health, or others?"}}

Example 7 - CANNOT IMPROVE (accept as-is):
Conversation History: 
  Q: "What time period?" A: "recent"
  Q: "How recent - past year, 2-3 years, or 5 years?" A: "fairly recent, maybe 2-4 years"
Latest Answer: "fairly recent, maybe 2-4 years"
→ {{"is_complete": true, "final_value": "2-4 years", "reasoning": "User has provided their best estimate after follow-up, accept it"}}

Example 8 - CANNOT IMPROVE (genuine uncertainty):
Conversation History:
  Q: "What geographic region?" A: "not sure, maybe global?"
  Q: "Would comparative regional studies work, or truly worldwide?" A: "I guess global, I'm not sure exactly"
Latest Answer: "I guess global, I'm not sure exactly"
→ {{"is_complete": true, "final_value": "global", "reasoning": "User is genuinely uncertain, accept their preference"}}

---

**Output Format:**

Return JSON with this structure:
{{
  "is_complete": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of your decision",
  "final_value": "clean, actionable value to integrate into query (only if is_complete=true)",
  "followup_question": "specific, focused follow-up question (only if is_complete=false)",
  "suggested_options": ["option1", "option2", "option3"] // optional, for follow-up questions
}}

**Important:**
- If is_complete=true: MUST provide final_value, followup_question should be null
- If is_complete=false: MUST provide followup_question, final_value should be null
- Keep followup_question focused on {aspect_name} only
- Make followup_question easy to answer (provide options when helpful)
- Be concise and practical in your evaluation

Now evaluate the latest answer:"""

# Shorter version for concise models (Token count matters)
UNIVERSAL_FOLLOWUP_PROMPT_CONCISE = """Evaluate if this answer is sufficient for query refinement.

Original Query: "{original_query}"
Aspect: {aspect_name} - {aspect_description}

Conversation:
{conversation_history}

Latest Answer: "{latest_answer}"

Is the answer:
✓ Specific and actionable? (e.g., "2020-2023" not "recent")
✓ Clear with no ambiguity?
✓ Doesn't conflict with query context?

If NO → Generate ONE focused follow-up question
If YES → Accept and provide final clean value

Return JSON:
{{
  "is_complete": true/false,
  "reasoning": "brief explanation",
  "final_value": "clean value (if complete)" or null,
  "followup_question": "specific question (if incomplete)" or null
}}"""