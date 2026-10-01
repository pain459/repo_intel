"""Pure project path mapping and explicit directory provisioning."""

from pathlib import Path
from uuid import UUID

from repo_intel.platform import AppPaths
from repo_intel.projects.models import ProjectPaths

_OWNER_DIRECTORY_MODE = 0o700


def registry_path(app_paths: AppPaths) -> Path:
    """Return the global registry location without touching the filesystem."""

    return app_paths.data_dir / "registry.sqlite3"


def project_paths(app_paths: AppPaths, repository_id: UUID) -> ProjectPaths:
    """Map a repository UUID to its generated platform-native locations."""

    if not isinstance(repository_id, UUID):
        raise TypeError("repository_id must be a UUID")
    leaf = str(repository_id)
    return ProjectPaths(
        data_dir=app_paths.data_dir / "projects" / leaf,
        cache_dir=app_paths.cache_dir / "projects" / leaf,
        log_dir=app_paths.log_dir / "projects" / leaf,
    )


def _create_owner_directories(path: Path) -> bool:
    missing: list[Path] = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent

    target_created = False
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=_OWNER_DIRECTORY_MODE)
        except FileExistsError:
            if not directory.is_dir():
                raise
        else:
            directory.chmod(_OWNER_DIRECTORY_MODE)
            target_created = directory == path
    return target_created


def provision_project_paths(paths: ProjectPaths) -> tuple[Path, ...]:
    """Create UUID storage leaves and return only leaves created by this call."""

    created: list[Path] = []
    for path in (paths.data_dir, paths.cache_dir, paths.log_dir):
        if _create_owner_directories(path):
            created.append(path)
    return tuple(created)
