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

__all__ = [
    "CleanupProviderProgress",
    "CleanupProviderState",
    "ProjectAvailability",
    "ProjectLifecycle",
    "ProjectPaths",
    "ProjectRecord",
    "ProjectStatus",
    "RepositoryIdentity",
    "project_paths",
    "provision_project_paths",
    "registry_path",
]
