"""Structured logging for Cascade."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    verbose: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Configure and return the Cascade logger."""
    logger = logging.getLogger("cascade")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_fmt = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path))
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger
