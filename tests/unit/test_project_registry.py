import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from repo_intel.errors import ExitCode, RepoIntelError
from repo_intel.projects.models import (
    CleanupProviderState,
    ProjectLifecycle,
    RepositoryIdentity,
)
from repo_intel.projects.registry import SCHEMA_VERSION, ProjectRegistry, RegistryWriteConflict

NOW = datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)


def _identity(root: Path) -> RepositoryIdentity:
    root.mkdir(parents=True)
    git_dir = root / ".git"
    git_dir.mkdir()
    metadata = git_dir.stat()
    return RepositoryIdentity(
        root=root.resolve(strict=True),
        git_dir=git_dir.resolve(strict=True),
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _create(
    registry: ProjectRegistry,
    root: Path,
    value: str = "11111111-1111-1111-1111-111111111111",
    *,
    display_name: str | None = None,
) -> tuple[UUID, RepositoryIdentity]:
    repository_id = UUID(value)
    identity = _identity(root)
    registry.create_initializing(
        repository_id,
        identity,
        display_name or root.name,
        NOW,
    )
    return repository_id, identity


def test_initial_schema_version_constraints_and_owner_permissions(tmp_path: Path) -> None:
    db_path = tmp_path / "private" / "registry.sqlite3"
    registry = ProjectRegistry(db_path)

    registry.initialize()

    assert db_path.stat().st_mode & 0o777 == 0o600
    assert db_path.parent.stat().st_mode & 0o777 == 0o700
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        projects_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
        ).fetchone()[0]
        cleanup_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cleanup_provider_state'"
        ).fetchone()[0]
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(cleanup_provider_state)"
        ).fetchall()
    assert "UNIQUE (canonical_root)" in projects_sql
    assert "UNIQUE (git_dir_device, git_dir_inode)" in projects_sql
    assert "CHECK" in projects_sql
    assert "CHECK" in cleanup_sql
    assert any(row[2] == "projects" and row[6] == "CASCADE" for row in foreign_keys)


def test_absent_registry_reads_are_empty_without_creating_storage(tmp_path: Path) -> None:
    data_dir = tmp_path / "not-created"
    registry = ProjectRegistry(data_dir / "registry.sqlite3")
    repository_id = UUID("11111111-1111-1111-1111-111111111111")

    assert registry.get_by_id(repository_id) is None
    assert registry.get_by_path(tmp_path.resolve()) is None
    assert registry.get_by_git_identity(1, 2) is None
    assert registry.list_projects() == ()
    assert registry.cleanup_progress(repository_id) == ()
    assert not data_dir.exists()


def test_records_round_trip_and_listing_is_canonical_root_then_uuid(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    id_z, identity_z = _create(
        registry,
        tmp_path / "z-root",
        "00000000-0000-0000-0000-000000000003",
    )
    id_a2, _ = _create(
        registry,
        tmp_path / "a-root-2",
        "00000000-0000-0000-0000-000000000002",
    )
    id_a1, identity_a1 = _create(
        registry,
        tmp_path / "a-root-1",
        "00000000-0000-0000-0000-000000000001",
    )

    records = registry.list_projects()

    assert [record.canonical_root.name for record in records] == [
        "a-root-1",
        "a-root-2",
        "z-root",
    ]
    assert registry.get_by_id(id_z) == records[2]
    assert registry.get_by_path(identity_a1.root) == records[0]
    assert registry.get_by_git_identity(identity_z.device, identity_z.inode) == records[2]
    assert {record.repository_id for record in records} == {id_z, id_a2, id_a1}
    assert all(record.created_at == NOW and record.updated_at == NOW for record in records)


def test_unique_path_and_git_identity_conflicts_are_distinguished_and_rolled_back(
    tmp_path: Path,
) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    first_id, first_identity = _create(registry, tmp_path / "first")
    second_identity = _identity(tmp_path / "second")

    with pytest.raises(RegistryWriteConflict) as path_conflict:
        registry.create_initializing(
            UUID("22222222-2222-2222-2222-222222222222"),
            first_identity,
            "duplicate path",
            NOW,
        )
    assert path_conflict.value.kind == "path"

    alias_identity = RepositoryIdentity(
        second_identity.root,
        second_identity.git_dir,
        first_identity.device,
        first_identity.inode,
    )
    with pytest.raises(RegistryWriteConflict) as identity_conflict:
        registry.create_initializing(
            UUID("33333333-3333-3333-3333-333333333333"),
            alias_identity,
            "duplicate identity",
            NOW,
        )
    assert identity_conflict.value.kind == "git_identity"
    assert [record.repository_id for record in registry.list_projects()] == [first_id]


def test_activate_relocate_and_invalid_lifecycle_transitions(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    repository_id, original = _create(registry, tmp_path / "original")

    with pytest.raises(RepoIntelError, match="active"):
        registry.relocate(repository_id, _identity(tmp_path / "too-early"), LATER)

    active = registry.activate(repository_id, LATER)
    assert active.lifecycle is ProjectLifecycle.ACTIVE
    assert active.updated_at == LATER
    with pytest.raises(RepoIntelError, match="initializing"):
        registry.activate(repository_id, LATER)

    relocated_identity = _identity(tmp_path / "relocated")
    relocated = registry.relocate(repository_id, relocated_identity, LATER)
    assert relocated.repository_id == repository_id
    assert relocated.canonical_root == relocated_identity.root
    assert relocated.git_dir_inode == relocated_identity.inode
    assert registry.get_by_path(original.root) is None

    removing = registry.begin_removal(repository_id, ("data",), LATER)
    assert removing.lifecycle is ProjectLifecycle.REMOVING
    with pytest.raises(RepoIntelError, match="initializing"):
        registry.activate(repository_id, LATER)
    with pytest.raises(RepoIntelError, match="active"):
        registry.relocate(repository_id, original, LATER)


def test_removal_can_begin_while_initializing_and_resume_with_new_providers(
    tmp_path: Path,
) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    repository_id, _ = _create(registry, tmp_path / "project")

    first = registry.begin_removal(repository_id, ("logs", "data"), NOW)
    resumed = registry.begin_removal(repository_id, ("cache", "data", "logs"), LATER)

    assert first.lifecycle is ProjectLifecycle.REMOVING
    assert resumed.lifecycle is ProjectLifecycle.REMOVING
    assert [item.provider_name for item in registry.cleanup_progress(repository_id)] == [
        "cache",
        "data",
        "logs",
    ]


def test_provider_reconciliation_failures_completion_and_cascade_deletion(
    tmp_path: Path,
) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    repository_id, _ = _create(registry, tmp_path / "project")
    registry.begin_removal(repository_id, ("cache", "data", "logs"), NOW)

    registry.mark_cleanup_completed(repository_id, "cache", LATER)
    registry.mark_cleanup_failed(repository_id, "data", "first safe summary", LATER)
    registry.mark_cleanup_failed(repository_id, "data", "replacement safe summary", LATER)
    progress = registry.reconcile_cleanup_providers(repository_id, ("qdrant",), LATER)

    assert [(item.provider_name, item.state.value) for item in progress] == [
        ("cache", "completed"),
        ("data", "pending"),
        ("logs", "pending"),
        ("qdrant", "pending"),
    ]
    assert next(item for item in progress if item.provider_name == "data").error_summary == (
        "replacement safe summary"
    )
    assert registry.delete_if_cleanup_complete(repository_id, ("cache", "data", "logs")) is False

    for provider_name in ("data", "logs", "qdrant"):
        registry.mark_cleanup_completed(repository_id, provider_name, LATER)
    assert registry.delete_if_cleanup_complete(repository_id, ("cache", "data", "logs")) is True
    assert registry.get_by_id(repository_id) is None
    assert registry.cleanup_progress(repository_id) == ()


def test_failed_relocation_rolls_back_the_original_record(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    first_id, _ = _create(registry, tmp_path / "first")
    second_id, second_identity = _create(
        registry,
        tmp_path / "second",
        "22222222-2222-2222-2222-222222222222",
    )
    registry.activate(first_id, NOW)
    registry.activate(second_id, NOW)
    before = registry.get_by_id(first_id)

    with pytest.raises(RegistryWriteConflict):
        registry.relocate(first_id, second_identity, LATER)

    assert registry.get_by_id(first_id) == before


def test_lock_contention_is_bounded_and_secret_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.sqlite3"
    registry = ProjectRegistry(db_path, busy_timeout_ms=10)
    repository_id, _ = _create(registry, tmp_path / "project")
    locker = sqlite3.connect(db_path)
    locker.execute("BEGIN IMMEDIATE")

    started = time.monotonic()
    try:
        with pytest.raises(RepoIntelError) as raised:
            registry.activate(repository_id, LATER)
    finally:
        locker.rollback()
        locker.close()

    assert time.monotonic() - started < 1
    assert raised.value.exit_code is ExitCode.DATA
    assert raised.value.hint is not None
    assert "locked" not in raised.value.message.lower()


@pytest.mark.parametrize("database_kind", ["malformed", "corrupt", "newer"])
def test_invalid_database_content_is_rejected_without_raw_details(
    tmp_path: Path,
    database_kind: str,
) -> None:
    db_path = tmp_path / "registry.sqlite3"
    secret = "SECRET_DATABASE_VALUE"
    if database_kind == "corrupt":
        db_path.write_bytes(b"not a sqlite database " + secret.encode())
    else:
        with sqlite3.connect(db_path) as connection:
            if database_kind == "malformed":
                connection.execute(f'CREATE TABLE projects ("{secret}" TEXT)')
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            else:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    registry = ProjectRegistry(db_path)
    with pytest.raises(RepoIntelError) as raised:
        registry.list_projects()

    presented = f"{raised.value.message} {raised.value.hint} {raised.value!r}"
    assert raised.value.exit_code is ExitCode.DATA
    assert secret not in presented
    assert "SELECT" not in presented


def test_cleanup_progress_round_trips_pending_and_completed_states(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.sqlite3")
    repository_id, _ = _create(registry, tmp_path / "project")
    registry.begin_removal(repository_id, ("cache",), NOW)

    assert registry.cleanup_progress(repository_id)[0].state is CleanupProviderState.PENDING
    registry.mark_cleanup_completed(repository_id, "cache", LATER)
    completed = registry.cleanup_progress(repository_id)[0]
    assert completed.state is CleanupProviderState.COMPLETED
    assert completed.error_summary is None
