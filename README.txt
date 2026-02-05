================================================================================
                          QueryRefine for macOS
                         Version 1.0.0 (February 2026)
================================================================================

QUICK START
-----------

1. Double-click "Configure Environment.command" to set up your API key
   (You'll need an OpenAI, Anthropic, or other compatible LLM API key)

2. Double-click "Run Query Refine.command" to start the application


WHAT'S INCLUDED
---------------

• QueryRefine.app - The main application
• Configure Environment.command - Setup wizard for API key
• Run Query Refine.command - Launch the command line interface
• sample.env - Template for environment variables
• framework.yaml - MPH dissertation and PICO refinement frameworks
• README.txt - This file


FIRST-TIME SETUP
----------------

1. Configure your environment:
   - Double-click "Configure Environment.command"
   - Choose your LLM provider (OpenAI, Anthropic, etc.)
   - Enter your API key when prompted
   - The script will create a .env file with your settings

2. Test the application:
   - Double-click "Run Query Refine.command"
   - Follow the interactive prompts to refine a search query


MANUAL USAGE (Advanced)
------------------------

You can also run QueryRefine from Terminal:

cd path/to/QueryRefine-Distribution
./QueryRefine.app/Contents/MacOS/QueryRefine --framework pico_advanced --query "your search query"

Available options:
  --framework FRAMEWORK   Use a specific framework (e.g., pico_advanced)
  --query QUERY          Initial query to refine
  --model MODEL          LLM model to use
  --interactive          Run in interactive mode
  --help                 Show all options


CUSTOM FRAMEWORKS
-----------------

You can create your own refinement frameworks:

1. Copy frameworks.yaml to a new file (e.g., my_framework.yaml)
2. Edit the aspects and questions according to your needs
3. Use it with: --framework path/to/my_framework.yaml


TROUBLESHOOTING
---------------

Issue: "Cannot be opened because it is from an unidentified developer"
Solution: Right-click QueryRefine.app → Open → confirm to open
   Or run in Terminal: xattr -cr QueryRefine.app

Issue: API key not working
Solution: Check your .env file has the correct key format:
   QUERY_REFINEMENT_LLM_API_KEY=your-key-here
   QUERY_REFINEMENT_LLM_PROVIDER=openai  # or anthropic, etc.

Issue: Command scripts don't work
Solution: Make them executable:
   chmod +x "Configure Environment.command"
   chmod +x "Run Query Refine.command"


SYSTEM REQUIREMENTS
-------------------

• macOS 10.15 (Catalina) or later
• Apple Silicon (M1/M2/M3) or Intel processor
• Internet connection (for API calls)
• Valid LLM API key (OpenAI, Anthropic, or compatible provider)


SUPPORT & DOCUMENTATION
------------------------

For more information, visit the project documentation or contact
the development team.


================================================================================
                     © 2026 QueryRefine Development Team
================================================================================
