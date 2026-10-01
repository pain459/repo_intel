from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.projects.cleanup import (
    CleanupCoordinator,
    CleanupResource,
    DirectoryCleanupProvider,
    default_cleanup_providers,
)
from repo_intel.projects.layout import project_paths, provision_project_paths
from repo_intel.projects.models import ProjectPaths, ProjectRecord, RepositoryIdentity
from repo_intel.projects.registry import ProjectRegistry

NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)
REPOSITORY_ID = UUID("11111111-1111-1111-1111-111111111111")


def _app_paths(root: Path) -> AppPaths:
    return AppPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        log_dir=root / "logs",
    )


def _registered_project(
    tmp_path: Path,
    *,
    active: bool = True,
    provision: bool = True,
) -> tuple[ProjectRegistry, AppPaths, ProjectRecord, ProjectPaths]:
    source = tmp_path / "source"
    git_dir = source / ".git"
    git_dir.mkdir(parents=True)
    metadata = git_dir.stat()
    identity = RepositoryIdentity(
        source.resolve(),
        git_dir.resolve(),
        metadata.st_dev,
        metadata.st_ino,
    )
    app_paths = _app_paths(tmp_path / "platform")
    registry = ProjectRegistry(app_paths.data_dir / "registry.sqlite3")
    project = registry.create_initializing(REPOSITORY_ID, identity, "source", NOW)
    paths = project_paths(app_paths, REPOSITORY_ID)
    if provision:
        provision_project_paths(paths)
    if active:
        project = registry.activate(REPOSITORY_ID, NOW)
    return registry, app_paths, project, paths


class RecordingProvider:
    def __init__(
        self,
        name: str,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.name = name
        self.failure = failure
        self.plan_calls = 0
        self.cleanup_calls = 0

    def plan(
        self,
        project: ProjectRecord,
        paths: ProjectPaths,
    ) -> tuple[CleanupResource, ...]:
        self.plan_calls += 1
        return (CleanupResource(self.name, "test", self.name, True, "remove"),)

    def cleanup(self, project: ProjectRecord, paths: ProjectPaths) -> None:
        self.cleanup_calls += 1
        if self.failure is not None:
            raise self.failure


class PlanningFailureProvider(RecordingProvider):
    def plan(
        self,
        project: ProjectRecord,
        paths: ProjectPaths,
    ) -> tuple[CleanupResource, ...]:
        raise RuntimeError("SECRET planning exception")


def _coordinator(
    registry: ProjectRegistry,
    app_paths: AppPaths,
    providers: tuple[RecordingProvider | DirectoryCleanupProvider, ...],
) -> CleanupCoordinator:
    return CleanupCoordinator(registry, app_paths, providers, clock=lambda: NOW)


def test_default_cleanup_plan_is_exact_and_deterministic(tmp_path: Path) -> None:
    registry, app_paths, project, paths = _registered_project(tmp_path)
    coordinator = CleanupCoordinator(
        registry,
        app_paths,
        default_cleanup_providers(),
        clock=lambda: NOW,
    )

    plan = coordinator.plan(project)

    observed = [
        (item.provider_name, item.kind, item.identifier, item.exists, item.action)
        for item in plan.resources
    ]
    assert observed == [
        ("cache", "directory", str(paths.cache_dir), True, "remove"),
        ("data", "directory", str(paths.data_dir), True, "remove"),
        ("logs", "directory", str(paths.log_dir), True, "remove"),
    ]
    assert plan.completed_provider_names == ()


def test_dry_run_plan_does_not_mutate_registry_or_filesystem(tmp_path: Path) -> None:
    registry, app_paths, project, paths = _registered_project(tmp_path)
    coordinator = CleanupCoordinator(
        registry,
        app_paths,
        default_cleanup_providers(),
        clock=lambda: NOW,
    )

    before = registry.get_by_id(REPOSITORY_ID)
    coordinator.plan(project)

    assert registry.get_by_id(REPOSITORY_ID) == before
    assert registry.cleanup_progress(REPOSITORY_ID) == ()
    assert all(path.is_dir() for path in (paths.data_dir, paths.cache_dir, paths.log_dir))


def test_dry_run_redacts_unknown_provider_planning_exceptions(tmp_path: Path) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    provider = PlanningFailureProvider("data")
    coordinator = _coordinator(registry, app_paths, (provider,))

    with pytest.raises(RepoIntelError) as raised:
        coordinator.plan(project)

    assert "SECRET" not in str(raised.value)


def test_initializing_project_with_incomplete_allocations_can_be_removed_by_uuid(
    tmp_path: Path,
) -> None:
    registry, app_paths, project, paths = _registered_project(
        tmp_path,
        active=False,
        provision=False,
    )
    paths.data_dir.mkdir(parents=True)
    coordinator = CleanupCoordinator(
        registry,
        app_paths,
        default_cleanup_providers(),
        clock=lambda: NOW,
    )

    result = coordinator.remove(project)

    assert result.exit_code is ExitCode.SUCCESS
    assert result.removed_registration is True
    assert registry.get_by_id(REPOSITORY_ID) is None
    assert not paths.data_dir.exists()


@pytest.mark.parametrize("invalid_kind", ["wrong-parent", "malformed-leaf", "file"])
def test_directory_cleanup_rejects_invalid_targets(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    _, _, project, valid_paths = _registered_project(tmp_path)
    target = valid_paths.data_dir
    if invalid_kind == "wrong-parent":
        target = tmp_path / "wrong-parent" / str(REPOSITORY_ID)
        target.mkdir(parents=True)
    elif invalid_kind == "malformed-leaf":
        target = valid_paths.data_dir.parent / "not-a-uuid"
        target.mkdir()
    else:
        target.rmdir()
        target.write_text("sentinel")
    paths = ProjectPaths(target, valid_paths.cache_dir, valid_paths.log_dir)
    provider = DirectoryCleanupProvider("data", lambda selected: selected.data_dir)

    with pytest.raises(RepoIntelError) as raised:
        provider.cleanup(project, paths)

    assert raised.value.exit_code is ExitCode.DATA
    assert target.exists()


def test_directory_cleanup_rejects_symlink_without_touching_external_sentinel(
    tmp_path: Path,
) -> None:
    _, _, project, paths = _registered_project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("keep")
    paths.data_dir.rmdir()
    paths.data_dir.symlink_to(external, target_is_directory=True)
    provider = DirectoryCleanupProvider("data", lambda selected: selected.data_dir)

    plan = provider.plan(project, paths)
    with pytest.raises(RepoIntelError):
        provider.cleanup(project, paths)

    assert plan[0].action == "refuse unsafe target"
    assert sentinel.read_text() == "keep"
    assert paths.data_dir.is_symlink()


def test_one_provider_failure_does_not_stop_independent_providers_and_is_redacted(
    tmp_path: Path,
) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    failing = RecordingProvider("cache", failure=RuntimeError("SECRET raw provider text"))
    succeeding = RecordingProvider("data")
    coordinator = _coordinator(registry, app_paths, (succeeding, failing))

    result = coordinator.remove(project)

    assert failing.cleanup_calls == 1
    assert succeeding.cleanup_calls == 1
    assert result.removed_registration is False
    assert result.exit_code is ExitCode.DATA
    assert "SECRET" not in repr(result)
    progress = {item.provider_name: item for item in registry.cleanup_progress(REPOSITORY_ID)}
    assert progress["cache"].state.value == "pending"
    assert progress["data"].state.value == "completed"
    assert "SECRET" not in (progress["cache"].error_summary or "")


def test_retry_skips_completed_provider_and_finishes_pending_provider(tmp_path: Path) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    cache = RecordingProvider("cache", failure=RuntimeError("first failure"))
    data = RecordingProvider("data")
    first = _coordinator(registry, app_paths, (cache, data)).remove(project)
    assert first.removed_registration is False
    cache.failure = None

    second = _coordinator(registry, app_paths, (cache, data)).remove(project)

    assert cache.cleanup_calls == 2
    assert data.cleanup_calls == 1
    assert second.completed_provider_names == ("cache", "data")
    assert second.removed_registration is True
    assert registry.get_by_id(REPOSITORY_ID) is None


def test_new_provider_is_reconciled_and_attempted_on_retry(tmp_path: Path) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    data = RecordingProvider("data", failure=RuntimeError("retry"))
    _coordinator(registry, app_paths, (data,)).remove(project)
    data.failure = None
    qdrant = RecordingProvider("qdrant")

    result = _coordinator(registry, app_paths, (data, qdrant)).remove(project)

    assert data.cleanup_calls == 2
    assert qdrant.cleanup_calls == 1
    assert result.removed_registration is True


def test_recorded_provider_missing_from_binary_blocks_deletion(tmp_path: Path) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    legacy = RecordingProvider("legacy", failure=RuntimeError("unavailable later"))
    _coordinator(registry, app_paths, (legacy,)).remove(project)
    current = RecordingProvider("data")

    result = _coordinator(registry, app_paths, (current,)).remove(project)

    assert result.removed_registration is False
    assert result.exit_code is ExitCode.DATA
    assert [failure.provider_name for failure in result.failures] == ["legacy"]
    assert registry.get_by_id(REPOSITORY_ID) is not None


def test_structured_external_service_failure_controls_result_exit_code(tmp_path: Path) -> None:
    registry, app_paths, project, _ = _registered_project(tmp_path)
    external = RecordingProvider(
        "qdrant",
        failure=RepoIntelError(
            "Qdrant cleanup failed safely.",
            ExitCode.EXTERNAL_SERVICE,
            "Start Qdrant and retry.",
        ),
    )
    local = RecordingProvider("data", failure=RuntimeError("local failure"))

    result = _coordinator(registry, app_paths, (local, external)).remove(project)

    assert result.exit_code is ExitCode.EXTERNAL_SERVICE
    qdrant_failure = next(item for item in result.failures if item.provider_name == "qdrant")
    assert qdrant_failure.summary == "Qdrant cleanup failed safely."
    assert qdrant_failure.hint == "Start Qdrant and retry."
