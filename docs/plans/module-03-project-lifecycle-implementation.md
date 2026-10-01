# Module 3: Project Registry, Storage, and Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable local project registration, platform-native generated-data allocations, relocation, status, and safe retryable cleanup on macOS and Ubuntu.

**Architecture:** A dedicated SQLite registry owns UUID identity, canonical-path uniqueness, lifecycle state, and cleanup progress. Focused repository-resolution, project-service, layout, and cleanup-provider components keep Git, filesystem, persistence, and CLI behavior independently testable; no external action runs inside a registry transaction.

**Tech Stack:** Python 3.12+, standard-library sqlite3/pathlib/uuid/datetime, Git through the existing shell-free CommandRunner, Typer, Pytest, Ruff, MyPy

**Spec:** docs/superpowers/specs/2026-10-01-module-03-project-lifecycle-design.md

**Execution status:** Complete. Tasks 1–7 passed locally, and exact reviewed
commit `fcb64191d01e14ded929690d78651b41b1ef7a92` passed the macOS and Ubuntu
GitHub Actions matrix in run 36883993923.

## Global Constraints

- Support macOS and Ubuntu only; preserve the existing unsupported-platform error.
- Keep all generated project state outside source repositories.
- Never create, edit, or delete .repo-intel.toml in Module 3.
- Use a dedicated data_dir/registry.sqlite3; do not reuse a future per-project index database.
- Use UUID-scoped data, cache, and log directories derived from AppPaths.
- Resolve Git only through CommandRunner with argument arrays, finite timeouts, and secret-safe errors.
- Treat remove --force as confirmation bypass only; never suppress provider failures.
- Perform no Git, filesystem, prompt, or provider work while holding a SQLite transaction.
- Delete a registry entry only after every recorded cleanup provider completes.
- Do not implement scanners, indexes, embeddings, Qdrant project data, or moved-repository auto-discovery.
- Preserve strict MyPy, Ruff, complete Pytest, package-build, CLI-smoke, and macOS/Ubuntu CI gates.

## Review Focus

1. Two processes initialize the same repository concurrently: Task 4 must prove one UUID wins and the other call returns that registration rather than creating or failing spuriously.
2. The registry is corrupt, locked, or from a newer schema: Task 3 must prove bounded, typed failure without partial migration or indefinite waiting.
3. Symlink aliases, same-filesystem moves, and a new clone at an old path: Tasks 2 and 4 must distinguish same identity, explicit relocation, and path reuse.
4. A UUID directory is replaced by a symlink or escapes its expected parent: Task 5 must refuse the target without following it or deleting the sentinel.
5. Cleanup is interrupted or the provider set changes between runs: Task 5 must retain progress, skip completed providers, reconcile new providers, and fail safely for missing recorded providers.

---

## Planned File Structure

- src/repo_intel/projects/models.py — immutable project, identity, status, path, and cleanup-progress records.
- src/repo_intel/projects/layout.py — pure UUID-to-path mapping and project-directory provisioning.
- src/repo_intel/projects/resolver.py — canonical Git-root and local identity resolution.
- src/repo_intel/projects/registry.py — schema-versioned SQLite persistence and short transactions.
- src/repo_intel/projects/service.py — registration, listing, status, availability, and relocation workflows.
- src/repo_intel/projects/cleanup.py — cleanup protocol, filesystem providers, orchestration, and recovery.
- src/repo_intel/projects/composition.py — production assembly from platform paths and runtime adapters.
- src/repo_intel/cli/projects.py — Typer commands and stable human-readable rendering.
- src/repo_intel/project_acceptance.py — isolated real-Git lifecycle acceptance workflow.
- scripts/acceptance_module_03.py — executable acceptance wrapper.
- tests/unit/test_project_layout.py — domain validation and platform allocation tests.
- tests/unit/test_repository_resolver.py — Git resolution and malformed-input tests.
- tests/unit/test_project_registry.py — schema, transaction, constraint, and progress tests.
- tests/unit/test_project_service.py — lifecycle, availability, relocation, and concurrency tests.
- tests/unit/test_project_cleanup.py — planning, ownership, partial-failure, and retry tests.
- tests/unit/test_cli_projects.py — CLI selector, confirmation, output, and exit-code tests.
- tests/unit/test_project_acceptance_runner.py — acceptance parser and safety-contract tests.
- tests/integration/test_project_lifecycle.py — real temporary Git and SQLite workflow tests.
- docs/testing/module-03-project-lifecycle-acceptance.md — manual and automated acceptance instructions.

### Task 1: Project records and platform-native allocations

**Files:**
- Create: src/repo_intel/projects/__init__.py
- Create: src/repo_intel/projects/models.py
- Create: src/repo_intel/projects/layout.py
- Create: tests/unit/test_project_layout.py

**Interfaces:**
- Consumes: repo_intel.platform.AppPaths and the existing RepoIntelError/ExitCode contract.
- Produces: ProjectLifecycle, ProjectAvailability, CleanupProviderState, RepositoryIdentity, ProjectRecord, ProjectPaths, CleanupProviderProgress, ProjectStatus, registry_path(), project_paths(), and provision_project_paths().

- [x] **Step 1: Write failing model and layout tests**

Add tests named:

- test_project_layout_is_uuid_scoped_under_every_platform_root
- test_registry_path_is_global_application_data
- test_provisioning_creates_only_project_directories_with_owner_permissions
- test_project_models_reject_relative_roots_invalid_uuid_paths_and_naive_times

Representative contract:

~~~python
repository_id = UUID("11111111-1111-1111-1111-111111111111")
paths = project_paths(app_paths, repository_id)
assert paths.data_dir == app_paths.data_dir / "projects" / str(repository_id)
assert paths.cache_dir == app_paths.cache_dir / "projects" / str(repository_id)
assert paths.log_dir == app_paths.log_dir / "projects" / str(repository_id)
assert registry_path(app_paths) == app_paths.data_dir / "registry.sqlite3"
~~~

- [x] **Step 2: Run the focused tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_layout.py -q

Expected: collection fails because repo_intel.projects does not exist.

- [x] **Step 3: Add the immutable records and pure path mapping**

Define:

~~~python
class ProjectLifecycle(StrEnum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    REMOVING = "removing"

class ProjectAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    REUSED = "reused"

class CleanupProviderState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"

@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    root: Path
    git_dir: Path
    device: int
    inode: int

@dataclass(frozen=True, slots=True)
class ProjectRecord:
    repository_id: UUID
    canonical_root: Path
    display_name: str
    git_dir_device: int
    git_dir_inode: int
    lifecycle: ProjectLifecycle
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True, slots=True)
class ProjectPaths:
    data_dir: Path
    cache_dir: Path
    log_dir: Path

@dataclass(frozen=True, slots=True)
class CleanupProviderProgress:
    provider_name: str
    state: CleanupProviderState
    error_summary: str | None
    updated_at: datetime

@dataclass(frozen=True, slots=True)
class ProjectStatus:
    project: ProjectRecord
    availability: ProjectAvailability
    paths: ProjectPaths
    cleanup: tuple[CleanupProviderProgress, ...]
~~~

Require absolute identity and project roots, nonnegative device/inode values,
nonblank display/provider names, and timezone-aware timestamps.

Define:

~~~python
def registry_path(app_paths: AppPaths) -> Path: ...
def project_paths(app_paths: AppPaths, repository_id: UUID) -> ProjectPaths: ...
def provision_project_paths(paths: ProjectPaths) -> tuple[Path, ...]: ...
~~~

Create the required platform-owned projects parents and the three UUID leaf
directories, apply mode 0o700 to directories created by this operation, and
return only UUID leaf paths that were newly created. Never create anything in
the repository root.

- [x] **Step 4: Run focused tests, lint, and typing**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_layout.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel/projects tests/unit/test_project_layout.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel/projects tests/unit/test_project_layout.py
~~~

Expected: all commands exit zero.

- [x] **Step 5: Commit Task 1**

~~~bash
git add src/repo_intel/projects tests/unit/test_project_layout.py
git commit -m "feat: define project lifecycle records"
~~~

### Task 2: Canonical Git repository resolution

**Files:**
- Create: src/repo_intel/projects/resolver.py
- Create: tests/unit/test_repository_resolver.py
- Modify: src/repo_intel/projects/__init__.py

**Interfaces:**
- Consumes: RepositoryIdentity and repo_intel.runtime.CommandRunner.
- Produces: resolve_repository(path: Path, runner: CommandRunner, *, timeout_seconds: float = 5.0) -> RepositoryIdentity.

- [x] **Step 1: Write failing resolver tests**

Use a recording fake CommandRunner and add tests for:

- root, nested, spaced, Unicode, and symlink-alias paths;
- Git missing from PATH;
- non-directory, non-Git, and bare repository inputs;
- timed-out, nonzero, empty, relative, extra-line, and malformed Git output;
- resolved Git directory stat failure; and
- secret sentinel text in stdout/stderr never appearing in RepoIntelError.

Pin these command boundaries:

~~~python
identity = resolve_repository(nested_path, runner)
assert identity.root == canonical_root
assert identity.git_dir == canonical_git_dir
assert (identity.device, identity.inode) == (
    canonical_git_dir.stat().st_dev,
    canonical_git_dir.stat().st_ino,
)
assert runner.which_calls == ["git"]
~~~

- [x] **Step 2: Run the resolver tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_repository_resolver.py -q

Expected: import fails because resolver.py does not exist.

- [x] **Step 3: Implement bounded Git resolution**

Implement resolve_repository() using shell-free Git invocations for
--is-inside-work-tree, --show-toplevel, and --absolute-git-dir. Require exactly
one normalized output value per query, require true for the work-tree check,
resolve both returned paths strictly, reject bare/non-work-tree repositories,
and capture the resolved Git directory's stat identity.

Map missing Git to DEPENDENCY and invalid paths, malformed output, command
failure, timeout, or stat failure to secret-safe DATA errors with actionable
hints.

- [x] **Step 4: Run focused and runtime regression checks**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_repository_resolver.py tests/unit/test_runtime_commands.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel/projects tests/unit/test_repository_resolver.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel/projects tests/unit/test_repository_resolver.py
~~~

Expected: all commands exit zero.

- [x] **Step 5: Commit Task 2**

~~~bash
git add src/repo_intel/projects tests/unit/test_repository_resolver.py
git commit -m "feat: resolve canonical git repositories"
~~~

### Task 3: Schema-versioned SQLite registry

**Files:**
- Create: src/repo_intel/projects/registry.py
- Create: tests/unit/test_project_registry.py
- Modify: src/repo_intel/projects/__init__.py

**Interfaces:**
- Consumes: ProjectRecord, RepositoryIdentity, CleanupProviderProgress, lifecycle/provider enums, and registry_path().
- Produces: SCHEMA_VERSION = 1, RegistryWriteConflict, and ProjectRegistry.

ProjectRegistry exposes:

~~~python
def initialize(self) -> None: ...
def create_initializing(
    self,
    repository_id: UUID,
    identity: RepositoryIdentity,
    display_name: str,
    now: datetime,
) -> ProjectRecord: ...
def get_by_id(self, repository_id: UUID) -> ProjectRecord | None: ...
def get_by_path(self, canonical_root: Path) -> ProjectRecord | None: ...
def get_by_git_identity(self, device: int, inode: int) -> ProjectRecord | None: ...
def list_projects(self) -> tuple[ProjectRecord, ...]: ...
def activate(self, repository_id: UUID, now: datetime) -> ProjectRecord: ...
def relocate(
    self,
    repository_id: UUID,
    identity: RepositoryIdentity,
    now: datetime,
) -> ProjectRecord: ...
def begin_removal(
    self,
    repository_id: UUID,
    provider_names: Sequence[str],
    now: datetime,
) -> ProjectRecord: ...
def reconcile_cleanup_providers(
    self,
    repository_id: UUID,
    provider_names: Sequence[str],
    now: datetime,
) -> tuple[CleanupProviderProgress, ...]: ...
def cleanup_progress(
    self,
    repository_id: UUID,
) -> tuple[CleanupProviderProgress, ...]: ...
def mark_cleanup_completed(
    self,
    repository_id: UUID,
    provider_name: str,
    now: datetime,
) -> None: ...
def mark_cleanup_failed(
    self,
    repository_id: UUID,
    provider_name: str,
    safe_summary: str,
    now: datetime,
) -> None: ...
def delete_if_cleanup_complete(
    self,
    repository_id: UUID,
    required_provider_names: Sequence[str],
) -> bool: ...
~~~

- [x] **Step 1: Write failing schema and registry tests**

Cover:

- initial schema, PRAGMA user_version = 1, foreign keys, and unique path and
  device/inode constraints;
- lookup and listing against an absent registry returning empty results
  without creating the data directory or database;
- deterministic canonical-root then UUID listing;
- every lifecycle mutation and invalid transition;
- removal beginning from active or initializing and resuming from removing;
- provider reconciliation, failure summary replacement, completion, and
  cascade deletion;
- rollback when a mutation fails;
- two connections contending within the bounded busy timeout;
- malformed database content, corrupt database bytes, and user_version newer
  than SCHEMA_VERSION; and
- safe translation of sqlite errors without SQL or raw values in output.

Representative assertion:

~~~python
registry.begin_removal(project.repository_id, ("cache", "data", "logs"), now)
registry.mark_cleanup_completed(project.repository_id, "cache", later)
progress = registry.cleanup_progress(project.repository_id)
assert [(item.provider_name, item.state.value) for item in progress] == [
    ("cache", "completed"),
    ("data", "pending"),
    ("logs", "pending"),
]
~~~

- [x] **Step 2: Run registry tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_registry.py -q

Expected: import fails because registry.py does not exist.

- [x] **Step 3: Implement schema and short transactions**

Create the projects and cleanup_provider_state tables exactly as specified.
Store UUIDs and absolute paths as canonical strings, device/inode as SQLite
integers, lifecycle/provider states as checked text, and aware UTC timestamps
as round-trippable text.

ProjectRegistry.__init__ accepts db_path: Path and busy_timeout_ms: int = 5000
and performs no I/O. Missing-database reads return empty/None without creating
the parent or database. initialize() is called only by a mutating workflow; it
creates the parent directory and database with owner-only permissions where
newly created, enables foreign keys, sets the bounded busy timeout, and
transactionally installs or validates schema version 1. Read-only access to
an incompatible existing schema fails without migration.

RegistryWriteConflict distinguishes path and Git-identity unique conflicts so
Task 4 can reread and classify concurrent initialization. Translate all other
sqlite failures to DATA without exposing SQL or stored values.

- [x] **Step 4: Run focused tests, then all persistence-adjacent tests**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_registry.py tests/unit/test_project_layout.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel/projects tests/unit/test_project_registry.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel/projects tests/unit/test_project_registry.py
~~~

Expected: all commands exit zero.

- [x] **Step 5: Commit Task 3**

~~~bash
git add src/repo_intel/projects tests/unit/test_project_registry.py
git commit -m "feat: persist the project registry"
~~~

### Task 4: Registration, status, listing, and relocation service

**Files:**
- Create: src/repo_intel/projects/service.py
- Create: tests/unit/test_project_service.py
- Create: tests/integration/test_project_lifecycle.py
- Modify: src/repo_intel/projects/__init__.py

**Interfaces:**
- Consumes: ProjectRegistry, AppPaths, RepositoryIdentity, resolve_repository(), project_paths(), and provision_project_paths().
- Produces: ProjectService with init(), projects(), status(), resolve_selector(), and relocate().

ProjectService exposes:

~~~python
def init(self, path: Path) -> ProjectStatus: ...
def projects(self) -> tuple[ProjectStatus, ...]: ...
def status(
    self,
    *,
    path: Path | None = None,
    repository_id: UUID | None = None,
) -> ProjectStatus: ...
def resolve_selector(
    self,
    *,
    path: Path | None = None,
    repository_id: UUID | None = None,
) -> ProjectRecord: ...
def relocate(
    self,
    repository_id: UUID,
    new_path: Path,
) -> ProjectStatus: ...
~~~

The constructor is:

~~~python
def __init__(
    self,
    registry: ProjectRegistry,
    app_paths: AppPaths,
    resolver: Callable[[Path], RepositoryIdentity],
    *,
    clock: Callable[[], datetime],
    uuid_factory: Callable[[], UUID],
    provision: Callable[[ProjectPaths], tuple[Path, ...]],
) -> None: ...
~~~

Production composition supplies aware-UTC, uuid4, and
provision_project_paths callables; tests inject deterministic values.

- [x] **Step 1: Write failing lifecycle-service tests**

Cover:

- first initialization and active promotion;
- same root/identity returning the same UUID;
- recovery from initializing after one provisioning failure;
- active, initializing, and removing conflict behavior;
- same identity at another path requiring relocate;
- same path with different identity reporting reused;
- missing-path status by UUID;
- deterministic multi-project listing and allocations;
- relocation preserving UUID and allocations while refreshing identity;
- relocation collision and non-active rejection; and
- two threads initializing one real temporary repository and receiving one
  UUID.

Add real-Git integration coverage for nested paths, symlink aliases,
same-filesystem moves, explicit relocation, missing paths, and replacement
repositories at the registered path.

- [x] **Step 2: Run service and integration tests and verify the red state**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_service.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/integration/test_project_lifecycle.py -q
~~~

Expected: imports fail because service.py does not exist.

- [x] **Step 3: Implement lifecycle orchestration**

For init(), call registry.initialize(), then classify path and identity
matches before creating a UUID. On RegistryWriteConflict, reread once and
apply the same classification so a concurrent same-repository registration is
idempotent. Keep failed provisioning in initializing and promote only after
all three directories exist. Listing and status against an absent registry
remain read-only and create nothing.

Availability inspection returns missing when the root is absent or no longer a
working tree, reused when current Git identity differs, and available only
when identity matches. Missing Git remains a DEPENDENCY error rather than
being mislabeled missing.

Reject simultaneous path and repository_id selectors with USAGE. UUID lookup
does not require the repository path to exist. Relocation requires active,
checks both destination uniqueness dimensions, and changes no project
allocation.

- [x] **Step 4: Run lifecycle, resolver, registry, lint, and typing checks**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_service.py tests/unit/test_repository_resolver.py tests/unit/test_project_registry.py tests/integration/test_project_lifecycle.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel/projects tests/unit/test_project_service.py tests/integration/test_project_lifecycle.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel/projects tests/unit/test_project_service.py tests/integration/test_project_lifecycle.py
~~~

Expected: all commands exit zero.

- [x] **Step 5: Commit Task 4**

~~~bash
git add src/repo_intel/projects tests/unit/test_project_service.py tests/integration/test_project_lifecycle.py
git commit -m "feat: manage project registration lifecycle"
~~~

### Task 5: Provider-based cleanup and recovery

**Files:**
- Create: src/repo_intel/projects/cleanup.py
- Create: tests/unit/test_project_cleanup.py
- Modify: tests/integration/test_project_lifecycle.py
- Modify: src/repo_intel/projects/__init__.py

**Interfaces:**
- Consumes: ProjectRegistry, ProjectRecord, ProjectPaths, cleanup progress, and project_paths().
- Produces: CleanupResource, CleanupFailure, CleanupPlan, CleanupResult, CleanupProvider, DirectoryCleanupProvider, default_cleanup_providers(), and CleanupCoordinator.

Define:

~~~python
@dataclass(frozen=True, slots=True)
class CleanupResource:
    provider_name: str
    kind: str
    identifier: str
    exists: bool
    action: str

class CleanupProvider(Protocol):
    name: str
    def plan(
        self,
        project: ProjectRecord,
        paths: ProjectPaths,
    ) -> tuple[CleanupResource, ...]: ...
    def cleanup(self, project: ProjectRecord, paths: ProjectPaths) -> None: ...

class CleanupCoordinator:
    def __init__(
        self,
        registry: ProjectRegistry,
        app_paths: AppPaths,
        providers: Sequence[CleanupProvider],
        *,
        clock: Callable[[], datetime],
    ) -> None: ...
    def plan(self, project: ProjectRecord) -> CleanupPlan: ...
    def remove(self, project: ProjectRecord) -> CleanupResult: ...

class DirectoryCleanupProvider:
    def __init__(
        self,
        name: str,
        select_path: Callable[[ProjectPaths], Path],
    ) -> None: ...

def default_cleanup_providers() -> tuple[CleanupProvider, ...]: ...
~~~

CleanupResult contains completed provider names, structured failures, a
removed_registration flag, and an exit_code derived without discarding safe
summaries: EXTERNAL_SERVICE when any provider reports it, otherwise DATA when
any provider fails, otherwise SUCCESS.

- [x] **Step 1: Write failing cleanup tests**

Cover:

- exact, deterministic plans for data, cache, and log UUID directories;
- dry-run planning with no registry or filesystem mutation;
- removal-by-UUID recovery for an initializing registration whose repository
  or allocations are incomplete;
- absent directory idempotency;
- rejection of wrong parent, malformed UUID leaf, file substitution, and
  symlink substitution with an external sentinel left untouched;
- all independent providers attempted after one failure;
- per-provider progress persisted after each attempt;
- retry skipping completed providers and finishing pending providers;
- a newly added provider reconciled on retry;
- a recorded provider missing from the current binary blocking deletion;
- raw provider exception text never persisted or rendered; and
- project row deletion only after every required provider completes.

Representative recovery assertion:

~~~python
first = coordinator.remove(project)
assert first.removed_registration is False
assert first.exit_code is ExitCode.DATA
second = repaired_coordinator.remove(project)
assert second.removed_registration is True
assert registry.get_by_id(project.repository_id) is None
~~~

- [x] **Step 2: Run cleanup tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_cleanup.py -q

Expected: import fails because cleanup.py does not exist.

- [x] **Step 3: Implement cleanup planning and orchestration**

Create three DirectoryCleanupProvider instances named cache, data, and logs;
sort all providers by stable name. Validate the expected projects parent,
exact UUID leaf, and lstat file type immediately before deletion. Never follow
a symlink and never remove the projects parent.

plan() is read-only. remove() moves active or initializing projects to
removing, resumes removing projects, reconciles provider names, skips
completed providers, records each provider outcome in a separate registry
transaction, continues independent providers, and calls
delete_if_cleanup_complete() only after the full attempt. Convert only
structured RepoIntelError metadata into CleanupFailure; replace unknown
exceptions with a fixed secret-safe DATA summary.

- [x] **Step 4: Run cleanup and lifecycle regression checks**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_cleanup.py tests/unit/test_project_service.py tests/integration/test_project_lifecycle.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel/projects tests/unit/test_project_cleanup.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel/projects tests/unit/test_project_cleanup.py
~~~

Expected: all commands exit zero.

- [x] **Step 5: Commit Task 5**

~~~bash
git add src/repo_intel/projects tests/unit/test_project_cleanup.py tests/integration/test_project_lifecycle.py
git commit -m "feat: add retryable project cleanup"
~~~

### Task 6: Project lifecycle CLI and user documentation

**Files:**
- Create: src/repo_intel/projects/composition.py
- Create: src/repo_intel/cli/projects.py
- Create: tests/unit/test_cli_projects.py
- Modify: src/repo_intel/cli/app.py
- Modify: tests/unit/test_cli.py
- Modify: README.md
- Modify: src/repo_intel/projects/__init__.py

**Interfaces:**
- Consumes: ProjectService, CleanupCoordinator, detect_platform(), AppPaths, SubprocessCommandRunner, ProjectStatus, CleanupPlan, and CleanupResult.
- Produces: build_project_commands(), init_command(), projects_app with relocate, status_command(), and remove_command().

Production composition returns:

~~~python
@dataclass(frozen=True, slots=True)
class ProjectCommands:
    service: ProjectService
    cleanup: CleanupCoordinator

def build_project_commands() -> ProjectCommands: ...
~~~

- [x] **Step 1: Write failing CLI tests**

Pin help and behavior for:

- repo-intel init [PATH], with current directory default;
- repo-intel projects and repo-intel projects relocate ID NEW_PATH;
- repo-intel projects against a missing registry returning an empty list
  without creating platform directories;
- repo-intel status [PATH] and --project-id, rejecting both together;
- repo-intel remove [PATH], --project-id, --dry-run, and --force;
- rejecting --dry-run with --force;
- dry run printing provider, exact identifier, existence, and action without a
  confirmation prompt;
- confirmation defaulting no, EOF cancellation, and explicit no printing
  Removal cancelled with exit zero;
- --force skipping the prompt but preserving a failed CleanupResult exit code;
- listing/status showing UUID, root, lifecycle, availability, allocation, and
  cleanup progress;
- path reuse and missing-path guidance pointing to --project-id; and
- typed errors omitting secret sentinel values.

- [x] **Step 2: Run CLI tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_cli_projects.py tests/unit/test_cli.py -q

Expected: CLI assertions fail because the project commands are absent.

- [x] **Step 3: Add production composition and thin Typer commands**

build_project_commands() resolves native AppPaths from Path.home() and
os.environ, constructs the registry without opening or creating it, creates
one SubprocessCommandRunner, binds resolve_repository(), builds
ProjectService, and installs the default cleanup providers.

Register init, status, and remove on the root app. Register projects as an
invoke-without-command Typer sub-application whose default callback lists
projects and whose relocate subcommand performs relocation.

Keep all lifecycle decisions in the service/coordinator. The CLI parses UUIDs,
defaults omitted paths to Path.cwd(), renders stable records, confirms removal
with default false, prints Removal cancelled on no/EOF, and exits with the
typed or aggregated result code.

- [x] **Step 4: Document exact CLI behavior and run command-level checks**

Document platform registry/allocation paths, every command form, path reuse,
relocation, dry-run, confirmation, --force semantics, partial cleanup retry,
missing-path recovery by UUID, and the promise that source configuration is
untouched.

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_cli_projects.py tests/unit/test_cli.py tests/integration/test_project_lifecycle.py -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel init --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel projects --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel projects relocate --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel status --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel remove --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check src/repo_intel tests/unit/test_cli_projects.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel tests/unit/test_cli_projects.py
~~~

Expected: all commands exit zero and help exposes every public contract.

- [x] **Step 5: Commit Task 6**

~~~bash
git add src/repo_intel/projects src/repo_intel/cli README.md tests/unit/test_cli.py tests/unit/test_cli_projects.py
git commit -m "feat: expose project lifecycle commands"
~~~

### Task 7: Isolated lifecycle acceptance and Module 3 gate

**Files:**
- Create: src/repo_intel/project_acceptance.py
- Create: scripts/acceptance_module_03.py
- Create: tests/unit/test_project_acceptance_runner.py
- Create: docs/testing/module-03-project-lifecycle-acceptance.md
- Modify: tests/integration/test_project_lifecycle.py
- Modify: .github/workflows/ci.yml
- Modify: docs/plans/module-03-project-lifecycle-implementation.md
- Modify: docs/plans/repo-intel-v1-execution-plan.md

**Interfaces:**
- Consumes: the complete Module 3 public CLI plus real temporary Git repositories.
- Produces: run_project_acceptance(argv: Sequence[str] | None = None) -> int and a safe one-command acceptance entry point.

- [x] **Step 1: Write failing acceptance-contract tests**

Test that the runner:

- documents that it uses only temporary repositories and isolated application
  roots;
- refuses to operate when its resolved application paths escape the temporary
  root;
- parses UUIDs and stable project output without accepting incomplete output;
- rejects a dry run that omits any owned location;
- detects source, .repo-intel.toml, unrelated-project, or sentinel mutation;
- reports the stage that failed without echoing captured secret sentinels; and
- exits zero only after the registry forgets the removed project.

- [x] **Step 2: Run acceptance tests and verify the red state**

Run: env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest tests/unit/test_project_acceptance_runner.py -q

Expected: import fails because project_acceptance.py does not exist.

- [x] **Step 3: Implement the isolated real-Git acceptance workflow**

Within one TemporaryDirectory, set HOME and every XDG root to isolated
subdirectories, create two real Git repositories with spaces and Unicode,
write a source file and user-authored .repo-intel.toml, and run the installed
repo-intel console without a shell.

Exercise:

1. nested-path init and idempotent repeated init;
2. a second independent project;
3. projects and status output;
4. a real repository move and projects relocate;
5. replacement of a registered repository path and path-reuse refusal;
6. exact remove --dry-run with no mutation;
7. safe cleanup failure by substituting one isolated UUID cache directory
   with a symlink to an isolated sentinel;
8. continued cleanup of independent providers and retained removing state;
9. repair of the isolated symlink and successful retry;
10. preservation of source, repository configuration, sentinel, and the
    unrelated project; and
11. final cleanup of the second project.

The wrapper only imports run_project_acceptance() and exits with its result.
It requires no model download, Docker action, Qdrant service, or real user
registry.

- [x] **Step 4: Add docs and both-platform CI acceptance**

Document:

~~~bash
uv run python scripts/acceptance_module_03.py
~~~

Add that command as a dedicated GitHub Actions step after tests on
macos-latest and ubuntu-latest. Extend CLI smoke checks for all Module 3 help
surfaces.

- [x] **Step 5: Run the complete local Module 3 gate**

Run:

~~~bash
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv sync --locked --all-groups
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff check .
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run mypy src/repo_intel tests scripts
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run pytest -q
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run python scripts/acceptance_module_03.py
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv build
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel init --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel projects --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel projects relocate --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel status --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run repo-intel remove --help
env UV_CACHE_DIR=/private/tmp/repo-intel-uv-cache uv run python -m repo_intel --help
git diff --check
~~~

Expected: every command exits zero; the acceptance runner reports MODULE 3
ACCEPTANCE PASSED and leaves no state outside its temporary root.

- [x] **Step 6: Review the complete Module 3 diff and commit the local gate**

Review from the Module 3 planning commit through HEAD for Critical and
Important correctness, safety, contract, and test gaps. Fix every such finding
and rerun Step 5.

~~~bash
git add src/repo_intel/project_acceptance.py scripts/acceptance_module_03.py tests/unit/test_project_acceptance_runner.py tests/integration/test_project_lifecycle.py docs/testing/module-03-project-lifecycle-acceptance.md .github/workflows/ci.yml docs/plans
git commit -m "ci: gate project lifecycle on both platforms"
~~~

Keep Module 3 In progress until the exact pushed reviewed commit passes both
GitHub Actions matrix jobs. Do not push; the user owns pushes.

- [x] **Step 7: Verify remote CI and close the Module 3 gate**

After the user pushes, verify Quality (macos-latest) and Quality
(ubuntu-latest) pass for the exact reviewed commit. Record the commit, local
commands, acceptance result, run URL, platform evidence, known limitations,
and Module 4 authorization in the execution index.

Mark Module 3 Complete only then and commit locally:

~~~bash
git add docs/plans/module-03-project-lifecycle-implementation.md docs/plans/repo-intel-v1-execution-plan.md
git commit -m "docs: close module three gate"
~~~

Closure evidence:

- Exact reviewed commit: `fcb64191d01e14ded929690d78651b41b1ef7a92`.
- Fresh local gate: locked dependency sync, Ruff lint and format, strict MyPy,
  259 Pytest tests, isolated Module 3 acceptance, source/wheel build, and Git
  whitespace validation all passed on macOS with Python 3.12.14.
- Acceptance result: `MODULE 3 ACCEPTANCE PASSED`.
- Cross-platform evidence: [GitHub Actions run 36883993923](https://github.com/pain459/repo_intel/actions/runs/36883993923)
  completed successfully; `Quality (macos-latest)` and
  `Quality (ubuntu-latest)` passed every step, including Module 3 acceptance.
- Known limitations: moved repositories require explicit relocation;
  automatic discovery, scanning, indexing, embeddings, Qdrant project data,
  and MCP remain deferred to later modules.
- Gate result: Module 3 is `Complete`, and Module 4 is authorized to enter
  planning.

## Plan Self-Review Record

- Spec coverage: every approved architecture, lifecycle, CLI, cleanup,
  failure, testing, and completion requirement has an owning task.
- Step scan: tasks are independently reviewable domain/layout, Git resolver,
  registry, service, cleanup, CLI, and acceptance deliverables; each step has
  one checkable result.
- Type consistency: RepositoryIdentity flows from Task 2 through the registry
  and service; ProjectRecord/ProjectPaths flow into cleanup; ProjectStatus and
  CleanupResult terminate at the CLI and acceptance runner.
- Review focus: concurrent initialization, hostile registry state, identity
  ambiguity, filesystem substitution, and evolving partial cleanup each have
  explicit tests in their owning task.
- Proportion: the plan fixes interfaces, observable behavior, tests, and gate
  commands without supplying production function bodies.
