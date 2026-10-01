"""Safe adapters for local process and HTTP access."""

from repo_intel.runtime.commands import CommandResult, CommandRunner, SubprocessCommandRunner
from repo_intel.runtime.http import (
    HttpState,
    JsonHttpClient,
    JsonResponse,
    UrllibJsonHttpClient,
)

__all__ = [
    "CommandResult",
    "CommandRunner",
    "HttpState",
    "JsonHttpClient",
    "JsonResponse",
    "SubprocessCommandRunner",
    "UrllibJsonHttpClient",
]
