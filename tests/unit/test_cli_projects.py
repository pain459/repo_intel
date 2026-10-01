from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from typer.testing import CliRunner

import repo_intel.cli.projects as cli_projects
import repo_intel.projects.composition as composition
from repo_intel.cli.app import app
from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths, PlatformKind
from repo_intel.projects.cleanup import CleanupFailure, CleanupPlan, CleanupResource, CleanupResult
from repo_intel.projects.composition import ProjectCommands
from repo_intel.projects.models import (
    CleanupProviderProgress,
    CleanupProviderState,
    ProjectAvailability,
    ProjectLifecycle,
    ProjectPaths,
    ProjectRecord,
    ProjectStatus,
)

runner = CliRunner()
NOW = datetime(2026, 10, 1, 11, tzinfo=UTC)
PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _status(root: Path = Path("/repo")) -> ProjectStatus:
    project = ProjectRecord(
        PROJECT_ID,
        root,
        root.name,
        1,
        2,
        ProjectLifecycle.ACTIVE,
        NOW,
        NOW,
    )
    return ProjectStatus(
        project,
        ProjectAvailability.AVAILABLE,
        ProjectPaths(Path("/data/project"), Path("/cache/project"), Path("/logs/project")),
        (
            CleanupProviderProgress(
                "cache",
                CleanupProviderState.PENDING,
                "retry needed",
                NOW,
            ),
        ),
    )


class FakeService:
    def __init__(self, status: ProjectStatus | None = None) -> None:
        self.value = status or _status()
        self.init_paths: list[Path] = []
        self.status_calls: list[tuple[Path | None, UUID | None]] = []
        self.relocations: list[tuple[UUID, Path]] = []
        self.raise_error: RepoIntelError | None = None

    def init(self, path: Path) -> ProjectStatus:
        self.init_paths.append(path)
        if self.raise_error is not None:
            raise self.raise_error
        return self.value

    def projects(self) -> tuple[ProjectStatus, ...]:
        if self.raise_error is not None:
            raise self.raise_error
        return (self.value,)

    def status(
        self,
        *,
        path: Path | None = None,
        repository_id: UUID | None = None,
    ) -> ProjectStatus:
        self.status_calls.append((path, repository_id))
        if path is not None and repository_id is not None:
            raise RepoIntelError("ambiguous", ExitCode.USAGE, "choose one")
        if self.raise_error is not None:
            raise self.raise_error
        return self.value

    def resolve_selector(
        self,
        *,
        path: Path | None = None,
        repository_id: UUID | None = None,
    ) -> ProjectRecord:
        self.status_calls.append((path, repository_id))
        if self.raise_error is not None:
            raise self.raise_error
        return self.value.project

    def relocate(self, repository_id: UUID, new_path: Path) -> ProjectStatus:
        self.relocations.append((repository_id, new_path))
        if self.raise_error is not None:
            raise self.raise_error
        return self.value


class FakeCleanup:
    def __init__(self, status: ProjectStatus) -> None:
        self.status = status
        self.plan_calls = 0
        self.remove_calls = 0
        self.result = CleanupResult(("cache", "data", "logs"), (), True)

    def plan(self, project: ProjectRecord) -> CleanupPlan:
        self.plan_calls += 1
        return CleanupPlan(
            project,
            (
                CleanupResource(
                    "data",
                    "directory",
                    str(self.status.paths.data_dir),
                    True,
                    "remove",
                ),
            ),
            (),
        )

    def remove(self, project: ProjectRecord) -> CleanupResult:
        self.remove_calls += 1
        return self.result


def _install_commands(
    monkeypatch: pytest.MonkeyPatch,
    service: FakeService | None = None,
) -> tuple[FakeService, FakeCleanup]:
    selected_service = service or FakeService()
    cleanup = FakeCleanup(selected_service.value)
    commands = ProjectCommands(
        service=cast("object", selected_service),  # type: ignore[arg-type]
        cleanup=cast("object", cleanup),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(cli_projects, "build_project_commands", lambda: commands)
    return selected_service, cleanup


def test_init_defaults_to_current_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _ = _install_commands(monkeypatch)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert service.init_paths == [Path.cwd()]
    assert f"Project ID: {PROJECT_ID}" in result.stdout
    assert "Lifecycle: active" in result.stdout


def test_projects_lists_stable_status_and_relocate_is_nested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _install_commands(monkeypatch)

    listing = runner.invoke(app, ["projects"])
    relocation = runner.invoke(
        app,
        ["projects", "relocate", str(PROJECT_ID), "/new/repository"],
    )

    assert listing.exit_code == 0
    assert "Root: /repo" in listing.stdout
    assert "Availability: available" in listing.stdout
    assert "Data: /data/project" in listing.stdout
    assert "Cleanup: cache=pending (retry needed)" in listing.stdout
    assert relocation.exit_code == 0
    assert service.relocations == [(PROJECT_ID, Path("/new/repository"))]


def test_production_empty_projects_list_does_not_create_platform_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_paths = AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
    )

    class StaticPlatform:
        kind = PlatformKind.MACOS

        def paths(self, *, home: Path, environ: object) -> AppPaths:
            return app_paths

    monkeypatch.setattr(composition, "detect_platform", lambda: StaticPlatform())
    commands = composition.build_project_commands()
    monkeypatch.setattr(cli_projects, "build_project_commands", lambda: commands)

    result = runner.invoke(app, ["projects"])

    assert result.exit_code == 0
    assert "No registered projects." in result.stdout
    assert not (tmp_path / "data").exists()


def test_status_accepts_path_or_project_id_and_rejects_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _install_commands(monkeypatch)

    by_path = runner.invoke(app, ["status", "/repo"])
    by_id = runner.invoke(app, ["status", "--project-id", str(PROJECT_ID)])
    ambiguous = runner.invoke(
        app,
        ["status", "/repo", "--project-id", str(PROJECT_ID)],
    )

    assert by_path.exit_code == 0
    assert by_id.exit_code == 0
    assert ambiguous.exit_code == int(ExitCode.USAGE)
    assert "Guidance: choose one" in ambiguous.stdout
    assert service.status_calls[:2] == [(Path("/repo"), None), (None, PROJECT_ID)]


def test_remove_rejects_force_with_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_commands(monkeypatch)

    result = runner.invoke(app, ["remove", "--dry-run", "--force"])

    assert result.exit_code == int(ExitCode.USAGE)
    assert "cannot be used together" in result.stdout


def test_remove_dry_run_prints_exact_plan_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cleanup = _install_commands(monkeypatch)

    result = runner.invoke(app, ["remove", "--project-id", str(PROJECT_ID), "--dry-run"])

    assert result.exit_code == 0
    assert "Provider: data" in result.stdout
    assert "Identifier: /data/project" in result.stdout
    assert "Exists: yes" in result.stdout
    assert "Action: remove" in result.stdout
    assert "Proceed" not in result.stdout
    assert cleanup.plan_calls == 1
    assert cleanup.remove_calls == 0


@pytest.mark.parametrize("input_text", ["n\n", ""])
def test_remove_defaults_to_cancellation_and_eof_is_successful(
    monkeypatch: pytest.MonkeyPatch,
    input_text: str,
) -> None:
    _, cleanup = _install_commands(monkeypatch)

    result = runner.invoke(app, ["remove", "--project-id", str(PROJECT_ID)], input=input_text)

    assert result.exit_code == 0
    assert "Removal cancelled" in result.stdout
    assert cleanup.remove_calls == 0


def test_remove_force_skips_prompt_and_preserves_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cleanup = _install_commands(monkeypatch)
    cleanup.result = CleanupResult(
        ("data",),
        (
            CleanupFailure(
                "qdrant",
                "Qdrant cleanup failed.",
                "Start Qdrant and retry.",
                ExitCode.EXTERNAL_SERVICE,
            ),
        ),
        False,
    )

    result = runner.invoke(
        app,
        ["remove", "--project-id", str(PROJECT_ID), "--force"],
    )

    assert result.exit_code == int(ExitCode.EXTERNAL_SERVICE)
    assert "Proceed" not in result.stdout
    assert "Qdrant cleanup failed." in result.stdout
    assert "Start Qdrant and retry." in result.stdout
    assert cleanup.remove_calls == 1


def test_path_recovery_errors_point_to_project_id_without_leaking_causes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeService()
    safe = RepoIntelError("Repository path is missing.", ExitCode.DATA, "Restore it.")
    safe.__cause__ = RuntimeError("SECRET_SENTINEL")
    service.raise_error = safe
    _install_commands(monkeypatch, service)

    result = runner.invoke(app, ["remove", "/missing/repository", "--dry-run"])

    assert result.exit_code == int(ExitCode.DATA)
    assert "--project-id" in result.stdout
    assert "SECRET_SENTINEL" not in result.stdout
