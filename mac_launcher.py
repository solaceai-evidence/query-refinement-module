"""Mac launcher entry-point for the packaged Query Refine application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure essential tiktoken encodings are registered even when namespace plugins are missing.
try:
    import tiktoken.registry as _tiktoken_registry
    from tiktoken.load import load_tiktoken_bpe as _load_tiktoken_bpe

    _CL100K_PAT = (
        r"""'(?:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"""
    )

    def _register_encoding(name: str, constructor) -> None:
        constructors = _tiktoken_registry.ENCODING_CONSTRUCTORS
        if constructors is None:
            constructors = {}
            _tiktoken_registry.ENCODING_CONSTRUCTORS = constructors
        constructors.setdefault(name, constructor)

    def _cl100k_base() -> dict:
        mergeable_ranks = _load_tiktoken_bpe(
            "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
            expected_hash="223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7",
        )
        special_tokens = {
            "<|endoftext|>": 100257,
            "<|fim_prefix|>": 100258,
            "<|fim_middle|>": 100259,
            "<|fim_suffix|>": 100260,
            "<|endofprompt|>": 100276,
        }
        return {
            "name": "cl100k_base",
            "pat_str": _CL100K_PAT,
            "mergeable_ranks": mergeable_ranks,
            "special_tokens": special_tokens,
        }

    _register_encoding("cl100k_base", _cl100k_base)
except Exception:  # pragma: no cover - defensive guard for missing optional deps
    pass

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