"""Provider-based, retryable cleanup for generated project resources."""

import shutil
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.platform import AppPaths
from repo_intel.projects.layout import project_paths
from repo_intel.projects.models import (
    CleanupProviderState,
    ProjectPaths,
    ProjectRecord,
)
from repo_intel.projects.registry import ProjectRegistry


@dataclass(frozen=True, slots=True)
class CleanupResource:
    """One exact generated resource shown in a cleanup plan."""

    provider_name: str
    kind: str
    identifier: str
    exists: bool
    action: str


@dataclass(frozen=True, slots=True)
class CleanupFailure:
    """Secret-safe failure metadata for one cleanup provider."""

    provider_name: str
    summary: str
    hint: str | None
    exit_code: ExitCode


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    """Read-only cleanup preview for one registered project."""

    project: ProjectRecord
    resources: tuple[CleanupResource, ...]
    completed_provider_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Aggregate outcome of an attempted provider cleanup."""

    completed_provider_names: tuple[str, ...]
    failures: tuple[CleanupFailure, ...]
    removed_registration: bool

    @property
    def exit_code(self) -> ExitCode:
        if any(failure.exit_code is ExitCode.EXTERNAL_SERVICE for failure in self.failures):
            return ExitCode.EXTERNAL_SERVICE
        if self.failures:
            return ExitCode.DATA
        return ExitCode.SUCCESS


class CleanupProvider(Protocol):
    """Plan and remove one kind of generated project resource."""

    name: str

    def plan(
        self,
        project: ProjectRecord,
        paths: ProjectPaths,
    ) -> tuple[CleanupResource, ...]: ...

    def cleanup(self, project: ProjectRecord, paths: ProjectPaths) -> None: ...


def _unsafe_target(provider_name: str) -> RepoIntelError:
    return RepoIntelError(
        f"The {provider_name} cleanup target is unsafe.",
        ExitCode.DATA,
        "Inspect the generated project directory and retry cleanup.",
    )


class DirectoryCleanupProvider:
    """Safely remove one exact UUID directory without following symlinks."""

    def __init__(
        self,
        name: str,
        select_path: Callable[[ProjectPaths], Path],
    ) -> None:
        if not name.strip():
            raise ValueError("cleanup provider name must not be blank")
        self.name = name
        self._select_path = select_path

    def _target(self, project: ProjectRecord, paths: ProjectPaths) -> tuple[Path, bool]:
        target = self._select_path(paths)
        expected_leaf = str(project.repository_id)
        if target.name != expected_leaf or target.parent.name != "projects":
            raise _unsafe_target(self.name)
        try:
            parsed_leaf = UUID(target.name)
        except ValueError as error:
            raise _unsafe_target(self.name) from error
        if parsed_leaf != project.repository_id or str(parsed_leaf) != target.name:
            raise _unsafe_target(self.name)

        parent = target.parent
        try:
            parent_metadata = parent.lstat()
        except FileNotFoundError:
            return target, False
        except OSError as error:
            raise _unsafe_target(self.name) from error
        if not stat.S_ISDIR(parent_metadata.st_mode) or parent.is_symlink():
            raise _unsafe_target(self.name)
        try:
            if parent.resolve(strict=True) != parent:
                raise _unsafe_target(self.name)
        except OSError as error:
            raise _unsafe_target(self.name) from error

        try:
            metadata = target.lstat()
        except FileNotFoundError:
            return target, False
        except OSError as error:
            raise _unsafe_target(self.name) from error
        if not stat.S_ISDIR(metadata.st_mode) or target.is_symlink():
            raise _unsafe_target(self.name)
        return target, True

    def plan(
        self,
        project: ProjectRecord,
        paths: ProjectPaths,
    ) -> tuple[CleanupResource, ...]:
        target, exists = self._target(project, paths)
        return (
            CleanupResource(
                provider_name=self.name,
                kind="directory",
                identifier=str(target),
                exists=exists,
                action="remove" if exists else "already absent",
            ),
        )

    def cleanup(self, project: ProjectRecord, paths: ProjectPaths) -> None:
        target, exists = self._target(project, paths)
        if not exists:
            return
        try:
            shutil.rmtree(target)
        except OSError as error:
            raise RepoIntelError(
                f"The {self.name} project directory could not be removed.",
                ExitCode.DATA,
                "Check directory ownership and permissions, then retry cleanup.",
            ) from error


def default_cleanup_providers() -> tuple[CleanupProvider, ...]:
    """Return the built-in generated-directory providers in stable order."""

    return (
        DirectoryCleanupProvider("cache", lambda paths: paths.cache_dir),
        DirectoryCleanupProvider("data", lambda paths: paths.data_dir),
        DirectoryCleanupProvider("logs", lambda paths: paths.log_dir),
    )


_UNKNOWN_FAILURE_SUMMARY = "Cleanup provider failed unexpectedly."
_UNKNOWN_FAILURE_HINT = "Resolve the provider issue and retry project removal."
_MISSING_PROVIDER_SUMMARY = "A recorded cleanup provider is unavailable."
_MISSING_PROVIDER_HINT = "Retry with a repo-intel version that includes this provider."


class CleanupCoordinator:
    """Coordinate durable cleanup progress across independent providers."""

    def __init__(
        self,
        registry: ProjectRegistry,
        app_paths: AppPaths,
        providers: Sequence[CleanupProvider],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        ordered = tuple(sorted(providers, key=lambda provider: provider.name))
        names = tuple(provider.name for provider in ordered)
        if any(not name.strip() for name in names):
            raise ValueError("cleanup provider names must not be blank")
        if len(set(names)) != len(names):
            raise ValueError("cleanup provider names must be unique")
        self._registry = registry
        self._app_paths = app_paths
        self._providers = ordered
        self._clock = clock

    def plan(self, project: ProjectRecord) -> CleanupPlan:
        """Describe cleanup resources without changing state."""

        paths = project_paths(self._app_paths, project.repository_id)
        resources: list[CleanupResource] = []
        for provider in self._providers:
            try:
                resources.extend(provider.plan(project, paths))
            except RepoIntelError:
                raise
            except Exception as error:
                raise RepoIntelError(
                    _UNKNOWN_FAILURE_SUMMARY,
                    ExitCode.DATA,
                    _UNKNOWN_FAILURE_HINT,
                ) from error
        completed = tuple(
            item.provider_name
            for item in self._registry.cleanup_progress(project.repository_id)
            if item.state is CleanupProviderState.COMPLETED
        )
        return CleanupPlan(project, tuple(resources), completed)

    @staticmethod
    def _failure(provider_name: str, error: Exception) -> CleanupFailure:
        if isinstance(error, RepoIntelError):
            return CleanupFailure(provider_name, error.message, error.hint, error.exit_code)
        return CleanupFailure(
            provider_name,
            _UNKNOWN_FAILURE_SUMMARY,
            _UNKNOWN_FAILURE_HINT,
            ExitCode.DATA,
        )

    def remove(self, project: ProjectRecord) -> CleanupResult:
        """Attempt every pending provider and persist resumable progress."""

        provider_names = tuple(provider.name for provider in self._providers)
        providers_by_name = {provider.name: provider for provider in self._providers}
        removing = self._registry.begin_removal(
            project.repository_id,
            provider_names,
            self._clock(),
        )
        progress = self._registry.reconcile_cleanup_providers(
            project.repository_id,
            provider_names,
            self._clock(),
        )
        paths = project_paths(self._app_paths, project.repository_id)
        failures: list[CleanupFailure] = []

        for item in progress:
            provider = providers_by_name.get(item.provider_name)
            if provider is None:
                failures.append(
                    CleanupFailure(
                        item.provider_name,
                        _MISSING_PROVIDER_SUMMARY,
                        _MISSING_PROVIDER_HINT,
                        ExitCode.DATA,
                    )
                )
                continue
            if item.state is CleanupProviderState.COMPLETED:
                continue
            try:
                provider.cleanup(removing, paths)
            except Exception as error:
                failure = self._failure(provider.name, error)
                failures.append(failure)
                self._registry.mark_cleanup_failed(
                    project.repository_id,
                    provider.name,
                    failure.summary,
                    self._clock(),
                )
            else:
                self._registry.mark_cleanup_completed(
                    project.repository_id,
                    provider.name,
                    self._clock(),
                )

        final_progress = self._registry.cleanup_progress(project.repository_id)
        completed = tuple(
            item.provider_name
            for item in final_progress
            if item.state is CleanupProviderState.COMPLETED
        )
        removed = False
        if not failures:
            removed = self._registry.delete_if_cleanup_complete(
                project.repository_id,
                provider_names,
            )
            if not removed:
                failures.append(
                    CleanupFailure(
                        "registry",
                        "Cleanup progress is incomplete.",
                        "Retry project removal to finish pending providers.",
                        ExitCode.DATA,
                    )
                )
        return CleanupResult(completed, tuple(failures), removed)


__all__ = [
    "CleanupCoordinator",
    "CleanupFailure",
    "CleanupPlan",
    "CleanupProvider",
    "CleanupResource",
    "CleanupResult",
    "DirectoryCleanupProvider",
    "default_cleanup_providers",
]
