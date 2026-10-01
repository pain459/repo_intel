from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from repo_intel.platform import AppPaths
from repo_intel.projects.layout import project_paths, provision_project_paths, registry_path
from repo_intel.projects.models import (
    CleanupProviderProgress,
    CleanupProviderState,
    ProjectLifecycle,
    ProjectPaths,
    ProjectRecord,
    RepositoryIdentity,
)


def _app_paths(root: Path) -> AppPaths:
    return AppPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        log_dir=root / "log",
    )


def test_project_layout_is_uuid_scoped_under_every_platform_root(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)
    repository_id = UUID("11111111-1111-1111-1111-111111111111")

    paths = project_paths(app_paths, repository_id)

    assert paths.data_dir == app_paths.data_dir / "projects" / str(repository_id)
    assert paths.cache_dir == app_paths.cache_dir / "projects" / str(repository_id)
    assert paths.log_dir == app_paths.log_dir / "projects" / str(repository_id)


def test_registry_path_is_global_application_data(tmp_path: Path) -> None:
    app_paths = _app_paths(tmp_path)

    assert registry_path(app_paths) == app_paths.data_dir / "registry.sqlite3"


def test_provisioning_creates_only_project_directories_with_owner_permissions(
    tmp_path: Path,
) -> None:
    app_paths = _app_paths(tmp_path / "platform")
    repository_id = UUID("22222222-2222-2222-2222-222222222222")
    repository_root = tmp_path / "source-repository"
    paths = project_paths(app_paths, repository_id)

    created = provision_project_paths(paths)

    assert created == (paths.data_dir, paths.cache_dir, paths.log_dir)
    assert not repository_root.exists()
    for leaf in created:
        assert leaf.is_dir()
        assert leaf.stat().st_mode & 0o777 == 0o700
        assert leaf.parent.stat().st_mode & 0o777 == 0o700

    assert provision_project_paths(paths) == ()


def test_project_models_reject_relative_roots_invalid_uuid_paths_and_naive_times(
    tmp_path: Path,
) -> None:
    aware = datetime(2026, 10, 1, tzinfo=UTC)
    repository_id = UUID("33333333-3333-3333-3333-333333333333")

    with pytest.raises(ValueError, match="absolute"):
        RepositoryIdentity(Path("relative"), tmp_path / ".git", 1, 2)
    with pytest.raises(ValueError, match="nonnegative"):
        RepositoryIdentity(tmp_path, tmp_path / ".git", -1, 2)
    with pytest.raises(ValueError, match="display_name"):
        ProjectRecord(
            repository_id,
            tmp_path,
            "   ",
            1,
            2,
            ProjectLifecycle.ACTIVE,
            aware,
            aware,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        ProjectRecord(
            repository_id,
            tmp_path,
            "project",
            1,
            2,
            ProjectLifecycle.ACTIVE,
            datetime(2026, 10, 1),
            aware,
        )
    with pytest.raises(ValueError, match="absolute"):
        ProjectPaths(Path("data"), tmp_path / "cache", tmp_path / "log")
    with pytest.raises(ValueError, match="provider_name"):
        CleanupProviderProgress("", CleanupProviderState.PENDING, None, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        CleanupProviderProgress(
            "data",
            CleanupProviderState.PENDING,
            None,
            datetime(2026, 10, 1),
        )

    invalid_repository_id: Any = "not-a-uuid"
    with pytest.raises(TypeError, match="UUID"):
        project_paths(_app_paths(tmp_path), invalid_repository_id)
