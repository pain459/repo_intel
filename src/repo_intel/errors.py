"""Shared error and process-exit contracts."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes for command-line and MCP callers."""

    SUCCESS = 0
    INTERNAL = 1
    USAGE = 2
    CONFIG = 3
    PLATFORM = 4
    DEPENDENCY = 5
    DATA = 6
    EXTERNAL_SERVICE = 7


class RepoIntelError(Exception):
    """Expected application failure with safe presentation metadata."""

    def __init__(
        self,
        message: str,
        exit_code: ExitCode,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.hint = hint

