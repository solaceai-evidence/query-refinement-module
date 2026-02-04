#!/usr/bin/env python3
"""
CLI entrypoint for PyInstaller-packaged QueryRefine application.
This is the main entry point for the standalone executable.
"""
import sys
from query_refinement_module.cli import main

if __name__ == "__main__":
    sys.exit(main())
