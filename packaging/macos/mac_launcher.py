"""Mac launcher entry-point for the packaged Query Refine application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from query_refinement_module.cli import main


def _resources_dir() -> Path:
    """Return the directory that holds bundled resource files."""

    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    resources = base_path / "Resources"
    if resources.is_dir():
        return resources
    return base_path


def _hydrate_env() -> None:
    """Load dotenv configuration and provide build-time defaults."""

    resources = _resources_dir()
    env_path = resources / ".env"
    sample_framework = resources / "sample_framework.yaml"

    if sample_framework.exists() and not os.getenv("REFINEMENT_FRAMEWORK_PATH"):
        os.environ["REFINEMENT_FRAMEWORK_PATH"] = str(sample_framework)

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)


if __name__ == "__main__":
    _hydrate_env()
    main()