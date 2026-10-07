# Query Refinement

A schema-guided conversational assistant that helps you turn a free-text research question into a structured, search-ready statement.

## How it works

1. **Log in** with the account you were given.
2. **Choose a refinement framework.** Each framework defines the dimensions of a well-formed question, such as population, intervention, comparator, outcome, timeframe or setting.
3. **Send your initial question.** The assistant works through each dimension that is missing or ambiguous, one question at a time. You can click a suggested answer or write your own.
4. **Stay in control** with the buttons under each question, or by typing commands:
   - `/back`, `/skip`, `/done`, `/clear`, `/restart`, `/submit` to navigate and finish
   - `/status`, `/steps`, `/help` to see where you are
5. **Review the result.** You get:
   - the refined question
   - a structured statement for each dimension
   - semantic and keyword statements
   - a Boolean search construction and search expansion levels
6. **Download** the structured output as JSON (for downstream tools) or as a Markdown report.
7. **Optionally give feedback** and choose whether your data may be kept for research.

Every session is saved with a full trace of each question, answer and command. If you close the page, you can resume an unfinished query the next time you log in.
