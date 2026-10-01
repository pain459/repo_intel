"""Isolated real-Git acceptance workflow for Module 3."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from repo_intel.errors import ExitCode
from repo_intel.platform import AppPaths, detect_platform
from repo_intel.projects.models import ProjectPaths
from repo_intel.runtime import CommandResult, SubprocessCommandRunner

OutputFunction = Callable[[str], None]


class AcceptanceFailure(RuntimeError):
    """A secret-safe failure of one Module 3 acceptance contract."""


@dataclass(frozen=True, slots=True)
class ParsedProjectOutput:
    """Required stable fields parsed from one CLI project record."""

    repository_id: UUID
    name: str
    root: Path
    lifecycle: str
    availability: str
    paths: ProjectPaths


@dataclass(frozen=True, slots=True)
class ProtectedFileState:
    """Content and metadata used to detect an unexpected file mutation."""

    path: Path
    content: bytes
    modified_ns: int
    mode: int


@dataclass(frozen=True, slots=True)
class AcceptanceOutcome:
    """Final proof required before the runner may report success."""

    registry_forgotten: bool


def validate_isolated_app_paths(root: Path, paths: AppPaths) -> None:
    """Reject any resolved application location outside the temporary root."""

    resolved_root = root.resolve(strict=True)
    for path in (paths.config_dir, paths.data_dir, paths.cache_dir, paths.log_dir):
        if not path.resolve().is_relative_to(resolved_root):
            raise AcceptanceFailure("resolved application path escapes the temporary root")


def parse_project_output(output: str) -> ParsedProjectOutput:
    """Parse one complete stable project record from CLI output."""

    required = ("Project ID", "Name", "Root", "Lifecycle", "Availability", "Data", "Cache", "Logs")
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(": ")
        if separator and key in required:
            if key in fields:
                raise AcceptanceFailure("project output is incomplete or ambiguous")
            fields[key] = value.strip()
    if any(not fields.get(name) for name in required):
        raise AcceptanceFailure("project output is incomplete or ambiguous")
    try:
        repository_id = UUID(fields["Project ID"])
        root = Path(fields["Root"])
        paths = ProjectPaths(
            Path(fields["Data"]),
            Path(fields["Cache"]),
            Path(fields["Logs"]),
        )
    except (TypeError, ValueError) as error:
        raise AcceptanceFailure("project output is incomplete or malformed") from error
    if not root.is_absolute():
        raise AcceptanceFailure("project output is incomplete or malformed")
    return ParsedProjectOutput(
        repository_id,
        fields["Name"],
        root,
        fields["Lifecycle"],
        fields["Availability"],
        paths,
    )


def validate_dry_run(output: str, paths: ProjectPaths) -> None:
    """Require one complete cleanup resource block for every owned location."""

    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in output.splitlines():
        key, separator, value = line.partition(": ")
        if not separator:
            continue
        if key == "Provider":
            current = {"Provider": value}
            blocks[value] = current
        elif current is not None and key in {"Kind", "Identifier", "Exists", "Action"}:
            current[key] = value
    expected = {
        "cache": str(paths.cache_dir),
        "data": str(paths.data_dir),
        "logs": str(paths.log_dir),
    }
    for provider_name, identifier in expected.items():
        block = blocks.get(provider_name)
        if (
            block is None
            or block.get("Kind") != "directory"
            or block.get("Identifier") != identifier
            or block.get("Exists") not in {"yes", "no"}
            or not block.get("Action")
        ):
            raise AcceptanceFailure(f"dry run is missing the {provider_name} owned location")


def capture_protected_files(paths: Sequence[Path]) -> tuple[ProtectedFileState, ...]:
    """Capture protected file content and metadata without displaying it."""

    states: list[ProtectedFileState] = []
    for path in paths:
        try:
            metadata = path.stat()
            states.append(
                ProtectedFileState(
                    path,
                    path.read_bytes(),
                    metadata.st_mtime_ns,
                    metadata.st_mode,
                )
            )
        except OSError as error:
            raise AcceptanceFailure(f"cannot inspect protected file: {path.name}") from error
    return tuple(states)


def assert_protected_files_unchanged(states: Sequence[ProtectedFileState]) -> None:
    """Fail when any protected source, config, unrelated, or sentinel file changed."""

    for before in states:
        try:
            metadata = before.path.stat()
            content = before.path.read_bytes()
        except OSError as error:
            raise AcceptanceFailure(f"protected file changed: {before.path.name}") from error
        if (
            content != before.content
            or metadata.st_mtime_ns != before.modified_ns
            or metadata.st_mode != before.mode
        ):
            raise AcceptanceFailure(f"protected file changed: {before.path.name}")


def ensure_command_succeeded(
    result: CommandResult,
    stage: str,
    *,
    allowed_codes: set[int] | None = None,
) -> None:
    """Validate a stage result without including its captured output in errors."""

    accepted = {0} if allowed_codes is None else allowed_codes
    if result.timed_out:
        raise AcceptanceFailure(f"{stage} timed out")
    if result.returncode not in accepted:
        raise AcceptanceFailure(f"{stage} failed with exit code {result.returncode}")


class _Host:
    def __init__(self, environment: Mapping[str, str]) -> None:
        self._runner = SubprocessCommandRunner(environ=environment)

    def executable(self, name: str) -> Path:
        executable = self._runner.which(name)
        if executable is None:
            raise AcceptanceFailure(f"required executable is missing: {name}")
        return executable

    def run(
        self,
        args: Sequence[str | Path | UUID],
        *,
        stage: str,
        allowed_codes: set[int] | None = None,
        timeout_seconds: float = 60,
    ) -> CommandResult:
        try:
            result = self._runner.run(
                tuple(str(argument) for argument in args),
                timeout_seconds=timeout_seconds,
            )
        except OSError as error:
            raise AcceptanceFailure(f"{stage} could not start") from error
        ensure_command_succeeded(result, stage, allowed_codes=allowed_codes)
        return result


def _pass(output: OutputFunction, message: str) -> None:
    output(f"[PASS] {message}")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _execute_acceptance(output: OutputFunction) -> AcceptanceOutcome:
    with tempfile.TemporaryDirectory(prefix="repo-intel-module-03-") as temporary:
        root = Path(temporary).resolve(strict=True)
        home = root / "home"
        home.mkdir()
        isolated_environment = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(root / "xdg" / "config"),
            "XDG_DATA_HOME": str(root / "xdg" / "data"),
            "XDG_CACHE_HOME": str(root / "xdg" / "cache"),
            "XDG_STATE_HOME": str(root / "xdg" / "state"),
        }
        adapter = detect_platform()
        app_paths = adapter.paths(home=home, environ=isolated_environment)
        validate_isolated_app_paths(root, app_paths)
        _pass(output, "native application paths are isolated under the temporary root")

        host = _Host(isolated_environment)
        git = host.executable("git")
        console = Path(sys.executable).parent / "repo-intel"
        if not console.is_file():
            console = host.executable("repo-intel")

        primary = root / "repositories" / "primary ü repository"
        secondary = root / "repositories" / "secondary repository"
        for repository in (primary, secondary):
            repository.mkdir(parents=True)
            host.run((git, "init", "--quiet", repository), stage="temporary Git initialization")
        nested = primary / "src" / "nested"
        nested.mkdir(parents=True)
        primary_source = primary / "src" / "source.py"
        primary_config = primary / ".repo-intel.toml"
        secondary_source = secondary / "other.py"
        _write_file(primary_source, "print('primary source')\n")
        _write_file(primary_config, "[repository]\nname = 'user-authored'\n")
        _write_file(secondary_source, "print('secondary source')\n")

        def cli(
            *arguments: str | Path | UUID,
            stage: str,
            allowed_codes: set[int] | None = None,
        ) -> CommandResult:
            return host.run(
                (console, *arguments),
                stage=stage,
                allowed_codes=allowed_codes,
            )

        first = parse_project_output(cli("init", nested, stage="nested project init").stdout)
        repeated = parse_project_output(
            cli("init", primary, stage="idempotent project init").stdout
        )
        if first.repository_id != repeated.repository_id:
            raise AcceptanceFailure("idempotent init returned a different project UUID")
        _pass(output, "nested and repeated initialization share one UUID")

        second = parse_project_output(cli("init", secondary, stage="second project init").stdout)
        if second.repository_id == first.repository_id:
            raise AcceptanceFailure("independent repositories received the same UUID")
        listing = cli("projects", stage="project listing").stdout
        registered_ids = (first.repository_id, second.repository_id)
        if not all(str(project_id) in listing for project_id in registered_ids):
            raise AcceptanceFailure("project listing omitted a registered UUID")
        parse_project_output(
            cli("status", "--project-id", first.repository_id, stage="project status").stdout
        )
        _pass(output, "listing and status expose both independent projects")

        moved = root / "repositories" / "moved primary repository"
        primary.rename(moved)
        missing = parse_project_output(
            cli(
                "status",
                "--project-id",
                first.repository_id,
                stage="missing project status",
            ).stdout
        )
        if missing.availability != "missing":
            raise AcceptanceFailure("moved repository was not reported missing before relocation")
        relocated = parse_project_output(
            cli(
                "projects",
                "relocate",
                first.repository_id,
                moved,
                stage="project relocation",
            ).stdout
        )
        if relocated.repository_id != first.repository_id or relocated.root != moved.resolve():
            raise AcceptanceFailure("relocation did not preserve UUID and refresh the root")
        _pass(output, "same-filesystem move requires and accepts explicit relocation")

        preserved_primary = root / "repositories" / "preserved primary source"
        moved.rename(preserved_primary)
        moved.mkdir()
        host.run((git, "init", "--quiet", moved), stage="replacement Git initialization")
        replacement_source = moved / "replacement.py"
        _write_file(replacement_source, "print('replacement source')\n")
        reused = parse_project_output(
            cli("status", "--project-id", first.repository_id, stage="path reuse status").stdout
        )
        if reused.availability != "reused":
            raise AcceptanceFailure("replacement repository path was not reported reused")
        refused = cli(
            "init",
            moved,
            stage="path reuse refusal",
            allowed_codes={int(ExitCode.DATA)},
        )
        if "reused" not in refused.stdout.lower():
            raise AcceptanceFailure("replacement repository initialization was not refused")
        _pass(output, "replacement repository is detected as path reuse")

        sentinel_dir = root / "external sentinel directory"
        sentinel_file = sentinel_dir / "sentinel.keep"
        _write_file(sentinel_file, "SECRET_SENTINEL_CONTENT")
        unrelated_markers = (
            second.paths.data_dir / "unrelated.marker",
            second.paths.cache_dir / "unrelated.marker",
            second.paths.log_dir / "unrelated.marker",
        )
        for marker in unrelated_markers:
            _write_file(marker, "unrelated project state")
        protected = capture_protected_files(
            (
                preserved_primary / "src" / "source.py",
                preserved_primary / ".repo-intel.toml",
                secondary_source,
                replacement_source,
                sentinel_file,
                *unrelated_markers,
            )
        )

        dry_run = cli(
            "remove",
            "--project-id",
            first.repository_id,
            "--dry-run",
            stage="cleanup dry run",
        )
        validate_dry_run(dry_run.stdout, first.paths)
        assert_protected_files_unchanged(protected)
        owned_paths = (first.paths.data_dir, first.paths.cache_dir, first.paths.log_dir)
        if not all(path.is_dir() for path in owned_paths):
            raise AcceptanceFailure("cleanup dry run mutated an owned location")
        _pass(output, "dry run reports every owned location without mutation")

        shutil.rmtree(first.paths.cache_dir)
        first.paths.cache_dir.symlink_to(sentinel_dir, target_is_directory=True)
        partial = cli(
            "remove",
            "--project-id",
            first.repository_id,
            "--force",
            stage="safe partial cleanup",
            allowed_codes={int(ExitCode.DATA)},
        )
        captured_output = f"{partial.stdout}{partial.stderr}"
        if "SECRET_SENTINEL_CONTENT" in captured_output:
            raise AcceptanceFailure("cleanup failure exposed sentinel content")
        partial_status_output = cli(
            "status",
            "--project-id",
            first.repository_id,
            stage="partial cleanup status",
        ).stdout
        partial_status = parse_project_output(partial_status_output)
        if partial_status.lifecycle != "removing":
            raise AcceptanceFailure("partial cleanup did not retain removing lifecycle")
        for expected_progress in ("cache=pending", "data=completed", "logs=completed"):
            if expected_progress not in partial_status_output:
                raise AcceptanceFailure("partial cleanup progress is incomplete")
        if first.paths.data_dir.exists() or first.paths.log_dir.exists():
            raise AcceptanceFailure("independent cleanup providers did not continue after failure")
        assert_protected_files_unchanged(protected)
        _pass(output, "unsafe cache substitution is refused while independent providers complete")

        first.paths.cache_dir.unlink()
        cli(
            "remove",
            "--project-id",
            first.repository_id,
            "--force",
            stage="cleanup retry",
        )
        forgotten = cli(
            "status",
            "--project-id",
            first.repository_id,
            stage="removed project lookup",
            allowed_codes={int(ExitCode.DATA)},
        )
        if "not registered" not in forgotten.stdout.lower():
            raise AcceptanceFailure("removed project remains addressable in the registry")
        remaining = cli("projects", stage="remaining project listing").stdout
        if str(first.repository_id) in remaining or str(second.repository_id) not in remaining:
            raise AcceptanceFailure("cleanup changed the unrelated project registration")
        assert_protected_files_unchanged(protected)
        _pass(output, "retry removes the first registration and preserves unrelated state")

        cli(
            "remove",
            "--project-id",
            second.repository_id,
            "--force",
            stage="second project cleanup",
        )
        final_listing = cli("projects", stage="final project listing").stdout
        registry_forgotten = "No registered projects." in final_listing
        if not registry_forgotten:
            raise AcceptanceFailure("final registry verification found a registered project")
        assert_protected_files_unchanged(protected[:5])
        _pass(
            output,
            "source, user configuration, replacement repository, and sentinel are preserved",
        )
        return AcceptanceOutcome(registry_forgotten=True)


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Run Module 3 against real temporary repositories and isolated application roots. "
            "It does not download models and does not use Docker or Qdrant. All generated state "
            "is deleted with the temporary directory when the run finishes."
        )
    )


def run_project_acceptance(argv: Sequence[str] | None = None) -> int:
    """Run the isolated Module 3 workflow and return a process exit code."""

    _parser().parse_args(argv)
    try:
        outcome = _execute_acceptance(print)
        if not outcome.registry_forgotten:
            raise AcceptanceFailure("final registry verification did not forget every project")
    except AcceptanceFailure as error:
        print(f"MODULE 3 ACCEPTANCE FAILED: {error}")
        return 1
    except Exception:
        print("MODULE 3 ACCEPTANCE FAILED: unexpected isolated workflow failure")
        return 1
    print("MODULE 3 ACCEPTANCE PASSED")
    return 0


__all__ = [
    "AcceptanceFailure",
    "AcceptanceOutcome",
    "ParsedProjectOutput",
    "ProtectedFileState",
    "assert_protected_files_unchanged",
    "capture_protected_files",
    "ensure_command_succeeded",
    "parse_project_output",
    "run_project_acceptance",
    "validate_dry_run",
    "validate_isolated_app_paths",
]
