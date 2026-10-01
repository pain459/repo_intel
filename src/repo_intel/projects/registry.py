"""Schema-versioned SQLite persistence for managed projects."""

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeVar
from uuid import UUID

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.projects.models import (
    CleanupProviderProgress,
    CleanupProviderState,
    ProjectLifecycle,
    ProjectRecord,
    RepositoryIdentity,
)

SCHEMA_VERSION = 1
_OWNER_DIRECTORY_MODE = 0o700
_OWNER_FILE_MODE = 0o600
_REGISTRY_HINT = "Check the registry file and permissions, then try again."
_LOCK_HINT = "Wait for the other repo-intel operation to finish, then try again."

ConflictKind = Literal["path", "git_identity", "repository_id"]
T = TypeVar("T")


class RegistryWriteConflict(RepoIntelError):
    """A stable uniqueness conflict raised by a registry mutation."""

    def __init__(self, kind: ConflictKind) -> None:
        super().__init__(
            "The project conflicts with an existing registry entry.",
            ExitCode.DATA,
            "Inspect the registered projects and use the existing project or relocate it.",
        )
        self.kind = kind


def _registry_error(*, locked: bool = False) -> RepoIntelError:
    hint = _LOCK_HINT if locked else _REGISTRY_HINT
    return RepoIntelError("The project registry operation failed.", ExitCode.DATA, hint)


def _lifecycle_error(expected: str) -> RepoIntelError:
    return RepoIntelError(
        f"The project must be {expected} for this operation.",
        ExitCode.DATA,
        "Run project status and finish the current lifecycle operation first.",
    )


def _missing_project_error() -> RepoIntelError:
    return RepoIntelError(
        "The project is not registered.",
        ExitCode.DATA,
        "List registered projects and select an existing project UUID.",
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("registry timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _project_from_row(row: sqlite3.Row) -> ProjectRecord:
    return ProjectRecord(
        repository_id=UUID(row["repository_id"]),
        canonical_root=Path(row["canonical_root"]),
        display_name=row["display_name"],
        git_dir_device=row["git_dir_device"],
        git_dir_inode=row["git_dir_inode"],
        lifecycle=ProjectLifecycle(row["lifecycle"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _progress_from_row(row: sqlite3.Row) -> CleanupProviderProgress:
    return CleanupProviderProgress(
        provider_name=row["provider_name"],
        state=CleanupProviderState(row["state"]),
        error_summary=row["error_summary"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _create_owner_directories(path: Path) -> None:
    missing: list[Path] = []
    candidate = path
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    for directory in reversed(missing):
        directory.mkdir(mode=_OWNER_DIRECTORY_MODE)
        directory.chmod(_OWNER_DIRECTORY_MODE)


class ProjectRegistry:
    """Persist project identity, lifecycle, and cleanup progress in SQLite."""

    def __init__(self, db_path: Path, busy_timeout_ms: int = 5000) -> None:
        if not db_path.is_absolute():
            raise ValueError("db_path must be absolute")
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be nonnegative")
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        target = f"{self._db_path.as_uri()}?mode=ro" if read_only else str(self._db_path)
        connection = sqlite3.connect(
            target,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
            uri=read_only,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @staticmethod
    def _user_version(connection: sqlite3.Connection) -> int:
        row = connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            raise _registry_error()
        return int(row[0])

    @staticmethod
    def _has_user_schema(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        return row is not None

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        if ProjectRegistry._user_version(connection) != SCHEMA_VERSION:
            raise _registry_error()

    def initialize(self) -> None:
        """Create or validate schema for a mutating workflow."""

        try:
            _create_owner_directories(self._db_path.parent)
            new_database = not self._db_path.exists()
            with self._connect(read_only=False) as connection:
                if new_database:
                    self._db_path.chmod(_OWNER_FILE_MODE)
                connection.execute("BEGIN IMMEDIATE")
                version = self._user_version(connection)
                if version == 0 and not self._has_user_schema(connection):
                    self._install_schema(connection)
                elif version != SCHEMA_VERSION:
                    raise _registry_error()
                connection.commit()
        except RepoIntelError:
            raise
        except sqlite3.OperationalError as error:
            raise _registry_error(locked="locked" in str(error).lower()) from error
        except (OSError, sqlite3.Error, ValueError) as error:
            raise _registry_error() from error

    @staticmethod
    def _install_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE projects (
                repository_id TEXT PRIMARY KEY,
                canonical_root TEXT NOT NULL,
                display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
                git_dir_device INTEGER NOT NULL CHECK (git_dir_device >= 0),
                git_dir_inode INTEGER NOT NULL CHECK (git_dir_inode >= 0),
                lifecycle TEXT NOT NULL
                    CHECK (lifecycle IN ('initializing', 'active', 'removing')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (canonical_root),
                UNIQUE (git_dir_device, git_dir_inode)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE cleanup_provider_state (
                project_id TEXT NOT NULL,
                provider_name TEXT NOT NULL CHECK (length(trim(provider_name)) > 0),
                state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
                error_summary TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project_id, provider_name),
                FOREIGN KEY (project_id) REFERENCES projects(repository_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _read(self, operation: Callable[[sqlite3.Connection], T], empty: T) -> T:
        if not self._db_path.exists():
            return empty
        try:
            with self._connect(read_only=True) as connection:
                self._validate_schema(connection)
                return operation(connection)
        except RepoIntelError:
            raise
        except sqlite3.OperationalError as error:
            raise _registry_error(locked="locked" in str(error).lower()) from error
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            raise _registry_error() from error

    def _write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        self.initialize()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect(read_only=False)
            self._validate_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            result = operation(connection)
            connection.commit()
            return result
        except RepoIntelError:
            if connection is not None:
                connection.rollback()
            raise
        except sqlite3.OperationalError as error:
            if connection is not None:
                connection.rollback()
            raise _registry_error(locked="locked" in str(error).lower()) from error
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            if connection is not None:
                connection.rollback()
            raise _registry_error() from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _select_project(
        connection: sqlite3.Connection,
        where: str,
        parameters: tuple[object, ...],
    ) -> ProjectRecord | None:
        row = connection.execute(
            "SELECT repository_id, canonical_root, display_name, git_dir_device, "
            "git_dir_inode, lifecycle, created_at, updated_at "
            f"FROM projects WHERE {where}",
            parameters,
        ).fetchone()
        return None if row is None else _project_from_row(row)

    def create_initializing(
        self,
        repository_id: UUID,
        identity: RepositoryIdentity,
        display_name: str,
        now: datetime,
    ) -> ProjectRecord:
        record = ProjectRecord(
            repository_id,
            identity.root,
            display_name,
            identity.device,
            identity.inode,
            ProjectLifecycle.INITIALIZING,
            now,
            now,
        )

        def create(connection: sqlite3.Connection) -> ProjectRecord:
            if self._select_project(connection, "canonical_root = ?", (str(identity.root),)):
                raise RegistryWriteConflict("path")
            if self._select_project(
                connection,
                "git_dir_device = ? AND git_dir_inode = ?",
                (identity.device, identity.inode),
            ):
                raise RegistryWriteConflict("git_identity")
            if self._select_project(connection, "repository_id = ?", (str(repository_id),)):
                raise RegistryWriteConflict("repository_id")
            connection.execute(
                "INSERT INTO projects "
                "(repository_id, canonical_root, display_name, git_dir_device, git_dir_inode, "
                "lifecycle, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(repository_id),
                    str(identity.root),
                    display_name,
                    identity.device,
                    identity.inode,
                    ProjectLifecycle.INITIALIZING.value,
                    _timestamp(now),
                    _timestamp(now),
                ),
            )
            return record

        return self._write(create)

    def get_by_id(self, repository_id: UUID) -> ProjectRecord | None:
        return self._read(
            lambda connection: self._select_project(
                connection, "repository_id = ?", (str(repository_id),)
            ),
            None,
        )

    def get_by_path(self, canonical_root: Path) -> ProjectRecord | None:
        return self._read(
            lambda connection: self._select_project(
                connection, "canonical_root = ?", (str(canonical_root),)
            ),
            None,
        )

    def get_by_git_identity(self, device: int, inode: int) -> ProjectRecord | None:
        return self._read(
            lambda connection: self._select_project(
                connection,
                "git_dir_device = ? AND git_dir_inode = ?",
                (device, inode),
            ),
            None,
        )

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        def select(connection: sqlite3.Connection) -> tuple[ProjectRecord, ...]:
            rows = connection.execute(
                "SELECT repository_id, canonical_root, display_name, git_dir_device, "
                "git_dir_inode, lifecycle, created_at, updated_at FROM projects "
                "ORDER BY canonical_root, repository_id"
            ).fetchall()
            return tuple(_project_from_row(row) for row in rows)

        return self._read(select, ())

    def _require_project(
        self,
        connection: sqlite3.Connection,
        repository_id: UUID,
    ) -> ProjectRecord:
        project = self._select_project(connection, "repository_id = ?", (str(repository_id),))
        if project is None:
            raise _missing_project_error()
        return project

    def activate(self, repository_id: UUID, now: datetime) -> ProjectRecord:
        def activate_project(connection: sqlite3.Connection) -> ProjectRecord:
            project = self._require_project(connection, repository_id)
            if project.lifecycle is not ProjectLifecycle.INITIALIZING:
                raise _lifecycle_error("initializing")
            connection.execute(
                "UPDATE projects SET lifecycle = ?, updated_at = ? WHERE repository_id = ?",
                (ProjectLifecycle.ACTIVE.value, _timestamp(now), str(repository_id)),
            )
            activated = self._select_project(
                connection, "repository_id = ?", (str(repository_id),)
            )
            assert activated is not None
            return activated

        return self._write(activate_project)

    def relocate(
        self,
        repository_id: UUID,
        identity: RepositoryIdentity,
        now: datetime,
    ) -> ProjectRecord:
        def relocate_project(connection: sqlite3.Connection) -> ProjectRecord:
            project = self._require_project(connection, repository_id)
            if project.lifecycle is not ProjectLifecycle.ACTIVE:
                raise _lifecycle_error("active")
            path_match = self._select_project(
                connection, "canonical_root = ?", (str(identity.root),)
            )
            if path_match is not None and path_match.repository_id != repository_id:
                raise RegistryWriteConflict("path")
            identity_match = self._select_project(
                connection,
                "git_dir_device = ? AND git_dir_inode = ?",
                (identity.device, identity.inode),
            )
            if identity_match is not None and identity_match.repository_id != repository_id:
                raise RegistryWriteConflict("git_identity")
            connection.execute(
                "UPDATE projects SET canonical_root = ?, git_dir_device = ?, "
                "git_dir_inode = ?, updated_at = ? WHERE repository_id = ?",
                (
                    str(identity.root),
                    identity.device,
                    identity.inode,
                    _timestamp(now),
                    str(repository_id),
                ),
            )
            relocated = self._select_project(
                connection, "repository_id = ?", (str(repository_id),)
            )
            assert relocated is not None
            return relocated

        return self._write(relocate_project)

    @staticmethod
    def _provider_names(provider_names: Sequence[str]) -> tuple[str, ...]:
        names = tuple(sorted(set(provider_names)))
        if any(not name.strip() for name in names):
            raise ValueError("provider names must not be blank")
        return names

    def _reconcile_in_transaction(
        self,
        connection: sqlite3.Connection,
        repository_id: UUID,
        provider_names: Sequence[str],
        now: datetime,
    ) -> None:
        for provider_name in self._provider_names(provider_names):
            connection.execute(
                "INSERT OR IGNORE INTO cleanup_provider_state "
                "(project_id, provider_name, state, error_summary, updated_at) "
                "VALUES (?, ?, ?, NULL, ?)",
                (
                    str(repository_id),
                    provider_name,
                    CleanupProviderState.PENDING.value,
                    _timestamp(now),
                ),
            )

    @staticmethod
    def _cleanup_rows(
        connection: sqlite3.Connection,
        repository_id: UUID,
    ) -> tuple[CleanupProviderProgress, ...]:
        rows = connection.execute(
            "SELECT provider_name, state, error_summary, updated_at "
            "FROM cleanup_provider_state WHERE project_id = ? ORDER BY provider_name",
            (str(repository_id),),
        ).fetchall()
        return tuple(_progress_from_row(row) for row in rows)

    def begin_removal(
        self,
        repository_id: UUID,
        provider_names: Sequence[str],
        now: datetime,
    ) -> ProjectRecord:
        def begin(connection: sqlite3.Connection) -> ProjectRecord:
            project = self._require_project(connection, repository_id)
            if project.lifecycle not in {
                ProjectLifecycle.INITIALIZING,
                ProjectLifecycle.ACTIVE,
                ProjectLifecycle.REMOVING,
            }:
                raise _lifecycle_error("active, initializing, or removing")
            connection.execute(
                "UPDATE projects SET lifecycle = ?, updated_at = ? WHERE repository_id = ?",
                (ProjectLifecycle.REMOVING.value, _timestamp(now), str(repository_id)),
            )
            self._reconcile_in_transaction(connection, repository_id, provider_names, now)
            removing = self._select_project(
                connection, "repository_id = ?", (str(repository_id),)
            )
            assert removing is not None
            return removing

        return self._write(begin)

    def reconcile_cleanup_providers(
        self,
        repository_id: UUID,
        provider_names: Sequence[str],
        now: datetime,
    ) -> tuple[CleanupProviderProgress, ...]:
        def reconcile(connection: sqlite3.Connection) -> tuple[CleanupProviderProgress, ...]:
            project = self._require_project(connection, repository_id)
            if project.lifecycle is not ProjectLifecycle.REMOVING:
                raise _lifecycle_error("removing")
            self._reconcile_in_transaction(connection, repository_id, provider_names, now)
            return self._cleanup_rows(connection, repository_id)

        return self._write(reconcile)

    def cleanup_progress(
        self,
        repository_id: UUID,
    ) -> tuple[CleanupProviderProgress, ...]:
        return self._read(
            lambda connection: self._cleanup_rows(connection, repository_id),
            (),
        )

    def mark_cleanup_completed(
        self,
        repository_id: UUID,
        provider_name: str,
        now: datetime,
    ) -> None:
        def complete(connection: sqlite3.Connection) -> None:
            self._require_project(connection, repository_id)
            cursor = connection.execute(
                "UPDATE cleanup_provider_state SET state = ?, error_summary = NULL, "
                "updated_at = ? WHERE project_id = ? AND provider_name = ?",
                (
                    CleanupProviderState.COMPLETED.value,
                    _timestamp(now),
                    str(repository_id),
                    provider_name,
                ),
            )
            if cursor.rowcount != 1:
                raise _registry_error()

        self._write(complete)

    def mark_cleanup_failed(
        self,
        repository_id: UUID,
        provider_name: str,
        safe_summary: str,
        now: datetime,
    ) -> None:
        if not safe_summary.strip():
            raise ValueError("safe_summary must not be blank")

        def fail(connection: sqlite3.Connection) -> None:
            self._require_project(connection, repository_id)
            cursor = connection.execute(
                "UPDATE cleanup_provider_state SET state = ?, error_summary = ?, "
                "updated_at = ? WHERE project_id = ? AND provider_name = ?",
                (
                    CleanupProviderState.PENDING.value,
                    safe_summary,
                    _timestamp(now),
                    str(repository_id),
                    provider_name,
                ),
            )
            if cursor.rowcount != 1:
                raise _registry_error()

        self._write(fail)

    def delete_if_cleanup_complete(
        self,
        repository_id: UUID,
        required_provider_names: Sequence[str],
    ) -> bool:
        required = set(self._provider_names(required_provider_names))

        def delete(connection: sqlite3.Connection) -> bool:
            project = self._require_project(connection, repository_id)
            if project.lifecycle is not ProjectLifecycle.REMOVING:
                raise _lifecycle_error("removing")
            progress = self._cleanup_rows(connection, repository_id)
            recorded = {item.provider_name for item in progress}
            if not required.issubset(recorded):
                return False
            if any(item.state is not CleanupProviderState.COMPLETED for item in progress):
                return False
            connection.execute(
                "DELETE FROM projects WHERE repository_id = ?",
                (str(repository_id),),
            )
            return True

        return self._write(delete)


__all__ = ["SCHEMA_VERSION", "ProjectRegistry", "RegistryWriteConflict"]
