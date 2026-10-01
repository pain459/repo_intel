"""Project lifecycle records and platform-native storage layout."""

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
    "CleanupProviderProgress",
    "CleanupProviderState",
    "ProjectAvailability",
    "ProjectLifecycle",
    "ProjectPaths",
    "ProjectRecord",
    "ProjectService",
    "ProjectStatus",
    "RepositoryIdentity",
    "SCHEMA_VERSION",
    "ProjectRegistry",
    "RegistryWriteConflict",
    "project_paths",
    "provision_project_paths",
    "registry_path",
    "resolve_repository",
]
