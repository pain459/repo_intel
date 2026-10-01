"""Application logging configuration."""

import logging
import sys
from typing import TextIO

from repo_intel.errors import ExitCode, RepoIntelError

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure the package logger without accumulating handlers."""
    normalized = level.upper()
    if normalized not in _LEVELS:
        raise RepoIntelError(
            f"Unknown log level: {level}",
            ExitCode.CONFIG,
            hint="Use DEBUG, INFO, WARNING, ERROR, or CRITICAL.",
        )

    logger = logging.getLogger("repo_intel")
    logger.handlers.clear()
    logger.setLevel(_LEVELS[normalized])
    logger.propagate = False

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
