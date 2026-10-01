"""Project lifecycle records and platform-native storage layout."""

from repo_intel.projects.cleanup import (
    CleanupCoordinator,
    CleanupFailure,
    CleanupPlan,
    CleanupProvider,
    CleanupResource,
    CleanupResult,
    DirectoryCleanupProvider,
    default_cleanup_providers,
)
from repo_intel.projects.composition import ProjectCommands, build_project_commands
from repo_intel.projects.layout import project_paths, provision_project_paths, registry_path
from repo_intel.projects.models import (
    CleanupProviderProgress,
    CleanupProviderState,
    ProjectAvailability,
    ProjectLifecycle,
    ProjectPaths,
    ProjectRecord,
    ProjectStatus,
    RepositoryIdentity,
)
from repo_intel.projects.registry import SCHEMA_VERSION, ProjectRegistry, RegistryWriteConflict
from repo_intel.projects.resolver import resolve_repository
from repo_intel.projects.service import ProjectService

__all__ = [
    "CleanupCoordinator",
    "CleanupFailure",
    "CleanupPlan",
    "CleanupProvider",
    "CleanupProviderProgress",
    "CleanupProviderState",
    "CleanupResource",
    "CleanupResult",
    "DirectoryCleanupProvider",
    "ProjectAvailability",
    "ProjectCommands",
    "ProjectLifecycle",
    "ProjectPaths",
    "ProjectRecord",
    "ProjectService",
    "ProjectStatus",
    "RepositoryIdentity",
    "SCHEMA_VERSION",
    "ProjectRegistry",
    "RegistryWriteConflict",
    "build_project_commands",
    "default_cleanup_providers",
    "project_paths",
    "provision_project_paths",
    "registry_path",
    "resolve_repository",
]
