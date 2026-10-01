import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from repo_intel.errors import RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.projects.cleanup import CleanupCoordinator, default_cleanup_providers
from repo_intel.projects.layout import provision_project_paths
from repo_intel.projects.models import ProjectAvailability
from repo_intel.projects.registry import ProjectRegistry
from repo_intel.projects.resolver import resolve_repository
from repo_intel.projects.service import ProjectService
from repo_intel.runtime import SubprocessCommandRunner


def _git_init(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _app_paths(root: Path) -> AppPaths:
    return AppPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        log_dir=root / "logs",
    )


def _service(root: Path) -> ProjectService:
    app_paths = _app_paths(root / "platform")
    runner = SubprocessCommandRunner()
    return ProjectService(
        ProjectRegistry(app_paths.data_dir / "registry.sqlite3"),
        app_paths,
        lambda path: resolve_repository(path, runner),
        clock=lambda: datetime.now(UTC),
        uuid_factory=uuid4,
        provision=provision_project_paths,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_real_git_nested_and_symlink_aliases_share_one_registration(tmp_path: Path) -> None:
    repository = tmp_path / "repository with ünicode"
    nested = repository / "src" / "package"
    _git_init(repository)
    nested.mkdir(parents=True)
    alias = tmp_path / "repository alias"
    alias.symlink_to(repository, target_is_directory=True)
    service = _service(tmp_path)

    nested_status = service.init(nested)
    alias_status = service.init(alias / "src")

    assert nested_status.project.repository_id == alias_status.project.repository_id
    assert len(service.projects()) == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_real_git_move_requires_relocation_and_preserves_registration(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    moved = tmp_path / "moved"
    _git_init(repository)
    service = _service(tmp_path)
    original = service.init(repository)
    repository.rename(moved)

    assert service.status(repository_id=original.project.repository_id).availability is (
        ProjectAvailability.MISSING
    )
    with pytest.raises(RepoIntelError, match="relocat"):
        service.init(moved)

    relocated = service.relocate(original.project.repository_id, moved)
    assert relocated.project.repository_id == original.project.repository_id
    assert relocated.project.canonical_root == moved.resolve()
    assert relocated.paths == original.paths


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_real_git_replacement_at_registered_path_is_reused(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    original_location = tmp_path / "original-location"
    _git_init(repository)
    service = _service(tmp_path)
    registered = service.init(repository)
    repository.rename(original_location)
    _git_init(repository)

    status = service.status(repository_id=registered.project.repository_id)

    assert status.availability is ProjectAvailability.REUSED
    with pytest.raises(RepoIntelError, match="reused"):
        service.init(repository)


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_two_threads_initializing_one_repository_receive_one_uuid(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _git_init(repository)
    service = _service(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(service.init, (repository, repository)))

    assert results[0].project.repository_id == results[1].project.repository_id
    assert len(service.projects()) == 1


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_real_cleanup_removes_only_generated_allocations(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _git_init(repository)
    source_file = repository / "source.py"
    config_file = repository / ".repo-intel.toml"
    source_file.write_text("print('keep me')\n")
    config_file.write_text("[repo-intel]\n")
    app_paths = _app_paths(tmp_path / "platform")
    runner = SubprocessCommandRunner()
    registry = ProjectRegistry(app_paths.data_dir / "registry.sqlite3")
    service = ProjectService(
        registry,
        app_paths,
        lambda path: resolve_repository(path, runner),
        clock=lambda: datetime.now(UTC),
        uuid_factory=uuid4,
        provision=provision_project_paths,
    )
    status = service.init(repository)
    coordinator = CleanupCoordinator(
        registry,
        app_paths,
        default_cleanup_providers(),
        clock=lambda: datetime.now(UTC),
    )

    result = coordinator.remove(status.project)

    assert result.removed_registration is True
    assert source_file.read_text() == "print('keep me')\n"
    assert config_file.read_text() == "[repo-intel]\n"
    assert not status.paths.data_dir.exists()
    assert not status.paths.cache_dir.exists()
    assert not status.paths.log_dir.exists()
