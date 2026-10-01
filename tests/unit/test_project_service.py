from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.projects.layout import project_paths, provision_project_paths
from repo_intel.projects.models import (
    ProjectAvailability,
    ProjectLifecycle,
    ProjectPaths,
    RepositoryIdentity,
)
from repo_intel.projects.registry import ProjectRegistry
from repo_intel.projects.service import ProjectService

NOW = datetime(2026, 10, 1, 9, tzinfo=UTC)
FIRST_ID = UUID("11111111-1111-1111-1111-111111111111")
SECOND_ID = UUID("22222222-2222-2222-2222-222222222222")


def _app_paths(root: Path) -> AppPaths:
    return AppPaths(
        config_dir=root / "config",
        data_dir=root / "data",
        cache_dir=root / "cache",
        log_dir=root / "logs",
    )


def _identity(root: Path) -> RepositoryIdentity:
    root.mkdir(parents=True, exist_ok=True)
    git_dir = root / ".git"
    git_dir.mkdir(exist_ok=True)
    metadata = git_dir.stat()
    return RepositoryIdentity(root.resolve(), git_dir.resolve(), metadata.st_dev, metadata.st_ino)


class MutableResolver:
    def __init__(self) -> None:
        self.identities: dict[Path, RepositoryIdentity | RepoIntelError] = {}

    def add(
        self,
        selected_path: Path,
        identity: RepositoryIdentity | RepoIntelError,
    ) -> None:
        self.identities[selected_path.resolve()] = identity

    def __call__(self, path: Path) -> RepositoryIdentity:
        value = self.identities[path.resolve()]
        if isinstance(value, RepoIntelError):
            raise value
        return value


def _service(
    tmp_path: Path,
    resolver: Callable[[Path], RepositoryIdentity],
    *,
    ids: tuple[UUID, ...] = (FIRST_ID, SECOND_ID),
    provision: Callable[[ProjectPaths], tuple[Path, ...]] = provision_project_paths,
) -> tuple[ProjectService, ProjectRegistry, AppPaths]:
    app_paths = _app_paths(tmp_path / "platform")
    registry = ProjectRegistry(app_paths.data_dir / "registry.sqlite3")
    remaining = iter(ids)
    service = ProjectService(
        registry,
        app_paths,
        resolver,
        clock=lambda: NOW,
        uuid_factory=lambda: next(remaining),
        provision=provision,
    )
    return service, registry, app_paths


def test_first_initialization_promotes_active_and_repeat_returns_same_uuid(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    identity = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, identity)
    service, _, app_paths = _service(tmp_path, resolver)

    first = service.init(root)
    repeated = service.init(root)

    assert first.project.repository_id == FIRST_ID
    assert first.project.lifecycle is ProjectLifecycle.ACTIVE
    assert first.availability is ProjectAvailability.AVAILABLE
    assert repeated.project.repository_id == FIRST_ID
    assert first.paths == project_paths(app_paths, FIRST_ID)
    assert all(
        path.is_dir() for path in (first.paths.data_dir, first.paths.cache_dir, first.paths.log_dir)
    )


def test_initializing_registration_is_repaired_after_provisioning_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    identity = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, identity)
    calls = 0

    def flaky_provision(paths: ProjectPaths) -> tuple[Path, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("SECRET provisioning detail")
        return provision_project_paths(paths)

    service, registry, _ = _service(tmp_path, resolver, provision=flaky_provision)

    with pytest.raises(RepoIntelError) as raised:
        service.init(root)
    stored = registry.get_by_id(FIRST_ID)
    assert stored is not None and stored.lifecycle is ProjectLifecycle.INITIALIZING
    assert "SECRET" not in str(raised.value)

    repaired = service.init(root)
    assert repaired.project.repository_id == FIRST_ID
    assert repaired.project.lifecycle is ProjectLifecycle.ACTIVE


def test_same_identity_at_new_path_requires_explicit_relocation(tmp_path: Path) -> None:
    root = tmp_path / "original"
    moved = tmp_path / "moved"
    identity = _identity(root)
    moved.mkdir()
    moved_git = moved / ".git"
    moved_git.mkdir()
    alias_identity = RepositoryIdentity(
        moved.resolve(),
        moved_git.resolve(),
        identity.device,
        identity.inode,
    )
    resolver = MutableResolver()
    resolver.add(root, identity)
    resolver.add(moved, alias_identity)
    service, _, _ = _service(tmp_path, resolver)
    service.init(root)

    with pytest.raises(RepoIntelError, match="relocat") as raised:
        service.init(moved)

    assert raised.value.exit_code is ExitCode.DATA


def test_removing_registration_cannot_be_reinitialized(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    identity = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, identity)
    service, registry, _ = _service(tmp_path, resolver)
    service.init(root)
    registry.begin_removal(FIRST_ID, ("data",), NOW)

    with pytest.raises(RepoIntelError, match="being removed"):
        service.init(root)


def test_replaced_repository_is_reported_reused_and_cannot_be_initialized(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    original = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, original)
    service, _, _ = _service(tmp_path, resolver)
    service.init(root)
    replacement_git = tmp_path / "replacement-git"
    replacement_git.mkdir()
    metadata = replacement_git.stat()
    replacement = RepositoryIdentity(
        root.resolve(),
        replacement_git.resolve(),
        metadata.st_dev,
        metadata.st_ino,
    )
    resolver.add(root, replacement)

    status = service.status(repository_id=FIRST_ID)
    with pytest.raises(RepoIntelError, match="reused"):
        service.init(root)

    assert status.availability is ProjectAvailability.REUSED


def test_uuid_status_survives_a_missing_source_path(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    identity = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, identity)
    service, _, _ = _service(tmp_path, resolver)
    service.init(root)
    resolver.add(
        root,
        RepoIntelError("missing", ExitCode.DATA, "restore the repository"),
    )

    status = service.status(repository_id=FIRST_ID)

    assert status.project.repository_id == FIRST_ID
    assert status.availability is ProjectAvailability.MISSING


def test_dependency_failure_is_not_mislabeled_as_missing(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    identity = _identity(root)
    resolver = MutableResolver()
    resolver.add(root, identity)
    service, _, _ = _service(tmp_path, resolver)
    service.init(root)
    resolver.add(root, RepoIntelError("Git missing", ExitCode.DEPENDENCY, "install Git"))

    with pytest.raises(RepoIntelError) as raised:
        service.status(repository_id=FIRST_ID)

    assert raised.value.exit_code is ExitCode.DEPENDENCY


def test_listing_is_deterministic_and_contains_uuid_allocations(tmp_path: Path) -> None:
    z_root = tmp_path / "z-project"
    a_root = tmp_path / "a-project"
    resolver = MutableResolver()
    resolver.add(z_root, _identity(z_root))
    resolver.add(a_root, _identity(a_root))
    service, _, app_paths = _service(tmp_path, resolver)
    service.init(z_root)
    service.init(a_root)

    projects = service.projects()

    assert [item.project.canonical_root.name for item in projects] == ["a-project", "z-project"]
    assert {item.paths for item in projects} == {
        project_paths(app_paths, FIRST_ID),
        project_paths(app_paths, SECOND_ID),
    }


def test_relocation_preserves_uuid_and_allocations_and_rejects_collisions(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    moved = tmp_path / "moved"
    resolver = MutableResolver()
    resolver.add(first, _identity(first))
    resolver.add(second, _identity(second))
    moved_identity = _identity(moved)
    resolver.add(moved, moved_identity)
    service, registry, app_paths = _service(tmp_path, resolver)
    service.init(first)
    service.init(second)

    relocated = service.relocate(FIRST_ID, moved)

    assert relocated.project.repository_id == FIRST_ID
    assert relocated.project.canonical_root == moved_identity.root
    assert relocated.paths == project_paths(app_paths, FIRST_ID)
    with pytest.raises(RepoIntelError):
        service.relocate(FIRST_ID, second)

    registry.begin_removal(FIRST_ID, ("data",), NOW)
    with pytest.raises(RepoIntelError, match="active"):
        service.relocate(FIRST_ID, first)


def test_selector_contract_rejects_ambiguous_or_unknown_selection(tmp_path: Path) -> None:
    resolver = MutableResolver()
    service, _, _ = _service(tmp_path, resolver)

    with pytest.raises(RepoIntelError) as ambiguous:
        service.status(path=tmp_path, repository_id=FIRST_ID)
    with pytest.raises(RepoIntelError) as unknown:
        service.status(repository_id=FIRST_ID)

    assert ambiguous.value.exit_code is ExitCode.USAGE
    assert unknown.value.exit_code is ExitCode.DATA
