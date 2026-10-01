"""Shell-free external command execution."""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

RunFunction = Callable[..., subprocess.CompletedProcess[str]]
WhichFunction = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Sanitized result of one external command."""

    args: tuple[str, ...]
    returncode: int
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    timed_out: bool = False


class CommandRunner(Protocol):
    """Discover and execute local programs without a shell."""

    def which(self, executable: str) -> Path | None: ...

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Production command runner backed by :mod:`subprocess`."""

    def __init__(
        self,
        *,
        which_fn: WhichFunction = shutil.which,
        run_fn: RunFunction = subprocess.run,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._which = which_fn
        self._run = run_fn
        self._environ = dict(os.environ if environ is None else environ)

    def which(self, executable: str) -> Path | None:
        discovered = self._which(executable)
        return Path(discovered) if discovered is not None else None

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
        stream: bool = False,
    ) -> CommandResult:
        command = tuple(args)
        command_environment = self._environ.copy()
        if env is not None:
            command_environment.update(env)

        try:
            completed = self._run(
                command,
                check=False,
                capture_output=not stream,
                env=command_environment,
                shell=False,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(command, 124, "", "", timed_out=True)

        return CommandResult(
            command,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )


__all__ = ["CommandResult", "CommandRunner", "SubprocessCommandRunner"]
