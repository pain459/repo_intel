"""Project registration and status lifecycle orchestration."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.projects.layout import project_paths
from repo_intel.projects.models import (
    ProjectAvailability,
    ProjectLifecycle,
    ProjectPaths,
    ProjectRecord,
    ProjectStatus,
    RepositoryIdentity,
)
from repo_intel.projects.registry import ProjectRegistry, RegistryWriteConflict


def _data_error(message: str, hint: str) -> RepoIntelError:
    return RepoIntelError(message, ExitCode.DATA, hint)


class ProjectService:
    """Coordinate repository identity, registry state, and generated paths."""

    def __init__(
        self,
        registry: ProjectRegistry,
        app_paths: AppPaths,
        resolver: Callable[[Path], RepositoryIdentity],
        *,
        clock: Callable[[], datetime],
        uuid_factory: Callable[[], UUID],
        provision: Callable[[ProjectPaths], tuple[Path, ...]],
    ) -> None:
        self._registry = registry
        self._app_paths = app_paths
        self._resolver = resolver
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._provision = provision

    @staticmethod
    def _same_identity(project: ProjectRecord, identity: RepositoryIdentity) -> bool:
        return (
            project.git_dir_device == identity.device
            and project.git_dir_inode == identity.inode
        )

    def _status(self, project: ProjectRecord) -> ProjectStatus:
        try:
            current = self._resolver(project.canonical_root)
        except RepoIntelError as error:
            if error.exit_code is ExitCode.DEPENDENCY:
                raise
            availability = ProjectAvailability.MISSING
        else:
            availability = (
                ProjectAvailability.AVAILABLE
                if self._same_identity(project, current)
                else ProjectAvailability.REUSED
            )
        return ProjectStatus(
            project=project,
            availability=availability,
            paths=project_paths(self._app_paths, project.repository_id),
            cleanup=self._registry.cleanup_progress(project.repository_id),
        )

    def _provision_and_activate(self, project: ProjectRecord) -> ProjectStatus:
        paths = project_paths(self._app_paths, project.repository_id)
        try:
            self._provision(paths)
        except RepoIntelError:
            raise
        except OSError as error:
            raise _data_error(
                "Project storage could not be provisioned.",
                "Check platform directory permissions and retry project initialization.",
            ) from error
        if not all(path.is_dir() for path in (paths.data_dir, paths.cache_dir, paths.log_dir)):
            raise _data_error(
                "Project storage provisioning is incomplete.",
                "Check platform directory permissions and retry project initialization.",
            )
        try:
            active = self._registry.activate(project.repository_id, self._clock())
        except RepoIntelError:
            current = self._registry.get_by_id(project.repository_id)
            if current is None or current.lifecycle is not ProjectLifecycle.ACTIVE:
                raise
            active = current
        return self._status(active)

    def _classify_initialization(self, identity: RepositoryIdentity) -> ProjectStatus | None:
        path_match = self._registry.get_by_path(identity.root)
        identity_match = self._registry.get_by_git_identity(identity.device, identity.inode)

        if path_match is not None:
            if not self._same_identity(path_match, identity):
                raise _data_error(
                    "The registered repository path has been reused by another repository.",
                    "Use project status to inspect it and remove or relocate the old registration.",
                )
            if (
                identity_match is not None
                and identity_match.repository_id != path_match.repository_id
            ):
                raise _data_error(
                    "The repository identity conflicts with another registration.",
                    "Inspect registered projects before continuing.",
                )
            if path_match.lifecycle is ProjectLifecycle.ACTIVE:
                return self._status(path_match)
            if path_match.lifecycle is ProjectLifecycle.INITIALIZING:
                return self._provision_and_activate(path_match)
            raise _data_error(
                "The project is being removed and cannot be initialized.",
                "Finish project removal before initializing this repository again.",
            )

        if identity_match is not None:
            raise _data_error(
                "The repository moved and requires explicit relocation.",
                "Run project relocate with the registered UUID and this new path.",
            )
        return None

    def init(self, path: Path) -> ProjectStatus:
        """Register a repository or repair its interrupted initialization."""

        self._registry.initialize()
        identity = self._resolver(path)
        classified = self._classify_initialization(identity)
        if classified is not None:
            return classified

        repository_id = self._uuid_factory()
        display_name = identity.root.name or str(identity.root)
        try:
            project = self._registry.create_initializing(
                repository_id,
                identity,
                display_name,
                self._clock(),
            )
        except RegistryWriteConflict:
            classified = self._classify_initialization(identity)
            if classified is not None:
                return classified
            raise
        return self._provision_and_activate(project)

    def projects(self) -> tuple[ProjectStatus, ...]:
        """List registered projects in registry order."""

        return tuple(self._status(project) for project in self._registry.list_projects())

    def resolve_selector(
        self,
        *,
        path: Path | None = None,
        repository_id: UUID | None = None,
    ) -> ProjectRecord:
        """Resolve one path-or-UUID selector without mutating registry state."""

        if path is not None and repository_id is not None:
            raise RepoIntelError(
                "Path and project UUID cannot be selected together.",
                ExitCode.USAGE,
                "Provide either a path or a project UUID.",
            )
        if repository_id is not None:
            project = self._registry.get_by_id(repository_id)
            if project is None:
                raise _data_error(
                    "The project is not registered.",
                    "List registered projects and choose an existing UUID.",
                )
            return project

        identity = self._resolver(Path.cwd() if path is None else path)
        path_match = self._registry.get_by_path(identity.root)
        if path_match is not None:
            return path_match
        identity_match = self._registry.get_by_git_identity(identity.device, identity.inode)
        if identity_match is not None:
            raise _data_error(
                "The repository moved and requires explicit relocation.",
                "Run project relocate with the registered UUID and this new path.",
            )
        raise _data_error(
            "The repository is not registered.",
            "Run project init for this repository first.",
        )

    def status(
        self,
        *,
        path: Path | None = None,
        repository_id: UUID | None = None,
    ) -> ProjectStatus:
        """Return current registration and live source availability."""

        return self._status(self.resolve_selector(path=path, repository_id=repository_id))

    def relocate(self, repository_id: UUID, new_path: Path) -> ProjectStatus:
        """Refresh an active registration after an explicit repository move."""

        project = self.resolve_selector(repository_id=repository_id)
        if project.lifecycle is not ProjectLifecycle.ACTIVE:
            raise _data_error(
                "The project must be active before relocation.",
                "Finish initialization or removal before relocating the project.",
            )
        identity = self._resolver(new_path)
        relocated = self._registry.relocate(repository_id, identity, self._clock())
        return self._status(relocated)


__all__ = ["ProjectService"]
