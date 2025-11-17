"""Helper utilities for configuring module logging outputs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

__all__ = ["configure_file_logging"]


def configure_file_logging(
    log_dir: str,
    *,
    filename: str = "application.log",
    level: int = logging.INFO,
    formatter: Optional[logging.Formatter] = None,
) -> Path:
    """Attach a file handler to the root logger, creating the directory if needed."""

    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / filename

    root_logger = logging.getLogger()
    formatter = formatter or logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in root_logger.handlers:
        existing_path = getattr(handler, "_qr_log_file", None)
        if existing_path and Path(existing_path) == log_file:
            return log_file

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler._qr_log_file = log_file  # type: ignore[attr-defined]

    root_logger.addHandler(handler)
    if root_logger.level == logging.NOTSET or root_logger.level > level:
        root_logger.setLevel(level)

    return log_file
