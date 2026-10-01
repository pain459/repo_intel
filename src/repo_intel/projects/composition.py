"""Production composition for project lifecycle commands."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from repo_intel.platform import detect_platform
from repo_intel.projects.cleanup import CleanupCoordinator, default_cleanup_providers
from repo_intel.projects.layout import provision_project_paths, registry_path
from repo_intel.projects.registry import ProjectRegistry
from repo_intel.projects.resolver import resolve_repository
from repo_intel.projects.service import ProjectService
from repo_intel.runtime import SubprocessCommandRunner


@dataclass(frozen=True, slots=True)
class ProjectCommands:
    """Production services used by project lifecycle CLI commands."""

    service: ProjectService
    cleanup: CleanupCoordinator


def build_project_commands() -> ProjectCommands:
    """Bind native paths and shell-free runtime dependencies without I/O."""

    adapter = detect_platform()
    app_paths = adapter.paths(home=Path.home(), environ=os.environ)
    registry = ProjectRegistry(registry_path(app_paths))
    runner = SubprocessCommandRunner()
    service = ProjectService(
        registry,
        app_paths,
        lambda path: resolve_repository(path, runner),
        clock=lambda: datetime.now(UTC),
        uuid_factory=uuid4,
        provision=provision_project_paths,
    )
    cleanup = CleanupCoordinator(
        registry,
        app_paths,
        default_cleanup_providers(),
        clock=lambda: datetime.now(UTC),
    )
    return ProjectCommands(service, cleanup)


__all__ = ["ProjectCommands", "build_project_commands"]
