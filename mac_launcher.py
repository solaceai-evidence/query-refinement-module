"""Mac launcher for the query refinement module CLI."""

from dotenv import load_dotenv
from query_refinement_module.cli import main

if __name__ == "__main__":
    load_dotenv(override=False)
    main()  