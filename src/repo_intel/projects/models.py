"""Immutable records shared by project lifecycle components."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID


class ProjectLifecycle(StrEnum):
    """Persistent stages of a managed project's lifecycle."""

    INITIALIZING = "initializing"
    ACTIVE = "active"
    REMOVING = "removing"


class ProjectAvailability(StrEnum):
    """Relationship between a registration and its current source path."""

    AVAILABLE = "available"
    MISSING = "missing"
    REUSED = "reused"


class CleanupProviderState(StrEnum):
    """Persistent execution state for one cleanup provider."""

    PENDING = "pending"
    COMPLETED = "completed"


def _require_absolute(path: Path, field_name: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be absolute")


def _require_nonnegative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be nonnegative")


def _require_nonblank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    """Canonical source root and stable identity of its Git directory."""

    root: Path
    git_dir: Path
    device: int
    inode: int

    def __post_init__(self) -> None:
        _require_absolute(self.root, "root")
        _require_absolute(self.git_dir, "git_dir")
        _require_nonnegative(self.device, "device")
        _require_nonnegative(self.inode, "inode")


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """Persistent global registration for a repository."""

    repository_id: UUID
    canonical_root: Path
    display_name: str
    git_dir_device: int
    git_dir_inode: int
    lifecycle: ProjectLifecycle
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.repository_id, UUID):
            raise TypeError("repository_id must be a UUID")
        _require_absolute(self.canonical_root, "canonical_root")
        _require_nonblank(self.display_name, "display_name")
        _require_nonnegative(self.git_dir_device, "git_dir_device")
        _require_nonnegative(self.git_dir_inode, "git_dir_inode")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """UUID-scoped generated storage owned by repo-intel."""

    data_dir: Path
    cache_dir: Path
    log_dir: Path

    def __post_init__(self) -> None:
        _require_absolute(self.data_dir, "data_dir")
        _require_absolute(self.cache_dir, "cache_dir")
        _require_absolute(self.log_dir, "log_dir")


@dataclass(frozen=True, slots=True)
class CleanupProviderProgress:
    """Last persisted state for one cleanup provider."""

    provider_name: str
    state: CleanupProviderState
    error_summary: str | None
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_nonblank(self.provider_name, "provider_name")
        _require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class ProjectStatus:
    """A registration enriched with live availability and cleanup state."""

    project: ProjectRecord
    availability: ProjectAvailability
    paths: ProjectPaths
    cleanup: tuple[CleanupProviderProgress, ...]
