"""Canonical Git worktree resolution."""

import stat
from os import stat_result
from pathlib import Path

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.projects.models import RepositoryIdentity
from repo_intel.runtime import CommandResult, CommandRunner

_GIT_GUIDANCE = "Install Git and ensure the git executable is available on PATH."
_REPOSITORY_GUIDANCE = "Choose an existing non-bare Git worktree and try again."


def _data_error(message: str) -> RepoIntelError:
    return RepoIntelError(message, ExitCode.DATA, _REPOSITORY_GUIDANCE)


def _one_output_value(result: CommandResult, query_name: str) -> str:
    if result.timed_out:
        raise _data_error(f"Git timed out while checking the repository {query_name}.")
    if result.returncode != 0:
        raise _data_error(f"Git could not determine the repository {query_name}.")

    normalized = result.stdout.strip()
    values = normalized.splitlines()
    if len(values) != 1 or not values[0].strip():
        raise _data_error(f"Git returned an invalid repository {query_name}.")
    return values[0].strip()


def _run_query(
    git: Path,
    source: Path,
    query: str,
    runner: CommandRunner,
    timeout_seconds: float,
) -> CommandResult:
    try:
        return runner.run(
            (str(git), "-C", str(source), "rev-parse", query),
            timeout_seconds=timeout_seconds,
        )
    except OSError as error:
        raise _data_error("Git could not inspect the repository.") from error


def _strict_directory(value: str, field_name: str) -> tuple[Path, stat_result]:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise _data_error(f"Git returned an invalid repository {field_name}.")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
    except (OSError, RuntimeError, ValueError) as error:
        raise _data_error(f"The resolved repository {field_name} is unavailable.") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise _data_error(f"The resolved repository {field_name} is not a directory.")
    return resolved, metadata


def resolve_repository(
    path: Path,
    runner: CommandRunner,
    *,
    timeout_seconds: float = 5.0,
) -> RepositoryIdentity:
    """Resolve an existing Git worktree to canonical filesystem identity."""

    git = runner.which("git")
    if git is None:
        raise RepoIntelError(
            "Git is required to resolve repositories.",
            ExitCode.DEPENDENCY,
            _GIT_GUIDANCE,
        )

    try:
        source = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _data_error("The repository path does not exist or cannot be resolved.") from error
    if not source.is_dir():
        raise _data_error("The repository path is not a directory.")

    inside = _one_output_value(
        _run_query(git, source, "--is-inside-work-tree", runner, timeout_seconds),
        "worktree state",
    )
    if inside != "true":
        raise _data_error("The selected path is not inside a Git worktree.")

    root_value = _one_output_value(
        _run_query(git, source, "--show-toplevel", runner, timeout_seconds),
        "root",
    )
    root, _ = _strict_directory(root_value, "root")
    git_dir_value = _one_output_value(
        _run_query(git, source, "--absolute-git-dir", runner, timeout_seconds),
        "Git directory",
    )

    git_dir, git_metadata = _strict_directory(git_dir_value, "Git directory")
    return RepositoryIdentity(
        root=root,
        git_dir=git_dir,
        device=git_metadata.st_dev,
        inode=git_metadata.st_ino,
    )


__all__ = ["resolve_repository"]
