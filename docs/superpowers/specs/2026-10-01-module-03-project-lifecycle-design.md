# Module 3: Project Registry, Storage, and Cleanup Design

**Status:** Approved

**Date:** 2026-10-01

**Parent design:** `docs/design/repo-intel-v1-design.md`

## Purpose

Module 3 gives each local repository a stable identity and an isolated,
platform-native allocation for generated data. It lets a user register,
inspect, relocate, and remove a project without changing or deleting source
files. Cleanup remains safe and retryable when a repository moves, disappears,
is replaced at the same path, or is only partially cleaned.

This design preserves the normal workflow: users clone `repo_intel`, work in
their repositories as usual, and can later remove every generated resource
owned by `repo_intel` for one project.

## Scope

Module 3 delivers:

- a user-level, schema-versioned SQLite project registry;
- stable UUID repository identities and canonical-path uniqueness;
- platform-native, UUID-scoped data, cache, and log locations;
- repository resolution and path-reuse detection;
- `init`, `projects`, `projects relocate`, `status`, and `remove`
  command flows;
- dry-run, interactive, and non-interactive cleanup;
- provider-based cleanup with durable partial-failure recovery; and
- macOS and Ubuntu unit, integration, CLI, and acceptance coverage.

Module 3 does not implement scanning, indexing, per-project metadata
databases, embeddings, Qdrant vectors, or automatic discovery of moved
repositories. It defines cleanup extension points for those later resources.
It does not create or delete `.repo-intel.toml`.

## Approved Decisions

1. The registry is a dedicated SQLite database, separate from future
   per-project index databases.
2. A successful removal deletes the project registration. A failed or
   interrupted removal retains a retryable `removing` record.
3. `init`, `status`, and `remove` accept an optional path that defaults
   to the current directory.
4. A path inside a working tree resolves to its canonical Git root.
5. Stable UUID selection is available for relocation and recovery when a
   repository path is missing or unusable.
6. `remove --force` skips confirmation only. It does not suppress cleanup
   failures or force deletion of registry state.
7. Cleanup never owns repository source or user-authored repository
   configuration.

## Architecture

### RepositoryResolver

`RepositoryResolver` uses Git through the existing injected command-runner
boundary. Given an explicit path or the current directory, it:

1. verifies that Git is available;
2. resolves a nested path to the working-tree root;
3. rejects non-Git paths and bare repositories;
4. resolves symlink aliases to an absolute canonical root;
5. obtains the absolute Git-directory path; and
6. captures the Git directory's filesystem device and inode.

The canonical root is the user-facing location. The Git-directory device and
inode are local identity evidence used to distinguish aliases, moves, and path
reuse. They are not presented as a permanent repository identity and may be
refreshed only by explicit relocation.

No marker or identifier is written into the source tree or Git directory.

### ProjectRegistry

`ProjectRegistry` owns `registry.sqlite3` under the platform data
directory. It owns schema creation, migrations, typed record conversion, and
short transactional mutations. It does not create project directories or run
cleanup providers.

Constructing the registry performs no I/O. Read-only lookup and listing treat
an absent database as an empty registry and do not create files or
directories. Schema creation and supported migrations occur only when a
mutating workflow opens the registry for writing; read-only access rejects an
incompatible existing schema without modifying it.

The initial schema contains:

- a `projects` table with UUID, canonical root, display name, Git-directory
  device and inode, lifecycle state, and UTC creation/update timestamps; and
- a `cleanup_provider_state` table keyed by project UUID and provider name,
  with pending/completed state, a safe failure category or summary, and an
  update timestamp.

The canonical root is unique. The Git-directory device/inode pair is also
unique while registered so path aliases cannot create a second registration.
Cleanup-provider rows use a foreign key with cascade deletion when the project
registration is removed.

The schema version is explicit. Supported migrations run transactionally.
A registry created by a newer unsupported schema fails readably and is never
modified by an older binary.

SQLite foreign keys are enabled. Mutations use short transactions and a
bounded busy timeout. No Git command, directory operation, confirmation
prompt, or provider cleanup runs while a database transaction is held.

### ProjectLayout

`ProjectLayout` is a pure mapping from platform paths and repository UUID to
owned locations:

```text
data_dir/
├── registry.sqlite3
└── projects/<repository-uuid>/

cache_dir/
└── projects/<repository-uuid>/

log_dir/
└── projects/<repository-uuid>/
```

The registry database is global application state and is never a project
cleanup target. Each project location is derived from a validated UUID rather
than user-controlled path text. New directories use owner-only permissions
subject to supported platform behavior and the user's existing parent
directory permissions.

Later modules may place their resources beneath the project data directory or
register another cleanup provider for externally owned state such as Qdrant
points.

### ProjectService

`ProjectService` coordinates the resolver, registry, and layout while
keeping CLI presentation separate. It implements initialization, lookup,
listing, status, and relocation state transitions.

### CleanupCoordinator

`CleanupCoordinator` consumes an ordered set of cleanup providers. Each
provider has a stable name and supports:

- `plan(project)`: describe exact owned resources and their current
  existence without mutation; and
- `cleanup(project)`: remove only those owned resources and safely succeed
  when they are already absent.

Module 3 provides data-directory, cache-directory, and log-directory
providers. Future modules add providers without changing the removal command
contract.

## Registry Lifecycle

The lifecycle states are:

- `initializing`: the registration exists but UUID-scoped locations may
  still need provisioning;
- `active`: registration and platform allocations are ready; and
- `removing`: confirmed cleanup is in progress or requires a retry.

Allowed transitions are:

```text
new          -> initializing
initializing -> active       (initialization succeeds or is retried)
initializing -> removing     (cleanup is confirmed instead)
active       -> removing     (cleanup is confirmed)
removing     -> removing     (cleanup is retried)
removing     -> deleted      (every provider completes)
```

An `initializing` record is not available to indexing or retrieval. A rerun
of `init` for the same repository repairs missing allocations and promotes
the record to `active`. An `active` registration cannot be reinitialized
under another UUID. A user may instead remove an `initializing` registration
by UUID; absent allocations are successful no-op cleanup resources.

A `removing` record cannot be reactivated by `init`. The user must finish
cleanup. Once every provider is complete, the registry removes the project and
its provider-state rows. A later initialization creates a new UUID.

## Command Contracts

### init

```bash
repo-intel init [PATH]
```

`PATH` defaults to the current directory. Initialization resolves the
canonical Git root and identity evidence before mutation.

- An active registration for the same root and Git identity is returned
  unchanged.
- An initializing registration is resumed.
- The same Git identity registered at a different root produces guidance to
  use `projects relocate`; it is not moved implicitly.
- A registered path occupied by different Git identity produces a path-reuse
  error.
- A removing registration produces guidance to finish cleanup.
- Otherwise a UUID and initializing row are created, project locations are
  provisioned, and the row becomes active.

If provisioning fails normally, the record remains initializing so the
operation is diagnosable and retryable. Initialization never modifies the
repository.

### projects

```bash
repo-intel projects
```

The command lists every registration ordered by canonical-root string and then
UUID. Each row shows the UUID, display name, canonical root, lifecycle state,
and observed availability:

- `available`: the path is the registered Git repository;
- `missing`: the stored path does not exist or is no longer a Git working
  tree; or
- `reused`: the path now contains different Git identity.

Listing is read-only and does not rewrite stale records.

### projects relocate

```bash
repo-intel projects relocate REPOSITORY_ID NEW_PATH
```

Relocation requires an `active` registration. It resolves and validates the
destination, rejects roots or Git identities owned by another registration,
preserves the UUID and all generated allocations, and transactionally updates
the canonical root and Git identity evidence.

Explicit UUID selection is the authorization to refresh identity evidence
when a legitimate move across filesystems changes device or inode. Relocation
does not copy, move, or inspect generated project data.

### status

```bash
repo-intel status [PATH]
repo-intel status --project-id REPOSITORY_ID
```

`PATH` defaults to the current directory. Path and UUID selectors are
mutually exclusive. UUID lookup supports missing, moved, or reused repository
paths.

Module 3 status reports registration identity, canonical root, lifecycle,
availability, platform allocations, and cleanup progress. Later modules may
compose index and service status onto this foundation.

### remove

```bash
repo-intel remove [PATH] --dry-run
repo-intel remove [PATH]
repo-intel remove [PATH] --force
repo-intel remove --project-id REPOSITORY_ID [--dry-run | --force]
```

`PATH` defaults to the current directory. Path and UUID selectors are
mutually exclusive. `--dry-run` and `--force` are mutually exclusive
because dry run never asks for confirmation.

Path selection requires identity to match the registration. Missing or reused
paths are recovered by UUID so a replacement repository cannot cause cleanup
of the wrong project's data.

`--force` only skips the prompt. It preserves validation, provider execution,
error reporting, exit status, and retry state.

## Path Reuse and Relocation

Canonical paths alone cannot distinguish a repository from a new clone placed
at the same location. Module 3 therefore compares stored Git-directory device
and inode evidence during implicit path lookup.

- Same path and same evidence is the registered project.
- Same evidence at a different path indicates a probable move and requires
  explicit relocation.
- Same path with different evidence is path reuse and is rejected.
- Missing paths remain manageable by UUID.

Filesystem identity is deliberately local evidence, not a content identity.
Explicit relocation may refresh it for cross-filesystem moves. Module 3 does
not infer identity from remote URLs, commit hashes, or mutable repository
content.

## Cleanup Protocol

### Planning

The coordinator requests a plan from every provider in stable provider-name
order. Each planned resource includes provider name, resource kind, exact safe
display identifier, existence state, and intended action.

Dry run prints the complete plan and performs no confirmation, lifecycle
transition, provider mutation, directory creation, or registry update. For a
partially cleaned project, it reports completed providers and the resources
still pending or already absent.

### Confirmed cleanup

After interactive confirmation or `--force`:

1. The registry moves an active or initializing project to `removing`, or
   resumes a project already in `removing`.
2. The coordinator reconciles the current provider set into pending provider
   rows. This includes providers added by a later software version.
3. Completed providers from an earlier attempt are skipped.
4. Every pending provider is attempted in deterministic order.
5. Each provider result is recorded in its own short transaction.
6. Independent providers continue after another provider fails.
7. Failures are aggregated into secret-safe, actionable output.
8. The command returns nonzero if any provider is incomplete.
9. The project row is deleted only when all registered providers complete.

If a recorded provider is unavailable in the running binary, removal fails
safely and retains the project rather than silently forgetting its resources.

### Filesystem ownership boundary

Filesystem providers may target only the exact UUID directory beneath the
expected platform-owned `projects` parent. Before deletion they validate the
UUID component, expected parent, and current file type. They never follow a
project-directory symlink. Unexpected paths, parent changes, or symlink
substitution are safety errors.

Providers are idempotent: an absent owned directory counts as complete.
Source paths, Git metadata, parent platform directories, the registry
database, and `.repo-intel.toml` are never provider targets.

Idempotency guarantees safe recovery while the `removing` record exists.
After fully successful cleanup, the deleted UUID is no longer known because
the approved design retains no tombstone.

## Error Handling

Expected failures use the existing `RepoIntelError` and exit-code contract:

- conflicting selectors and option combinations use `USAGE`;
- an unavailable Git executable uses `DEPENDENCY`;
- invalid repositories, duplicate identities, path reuse, unsafe cleanup
  targets, registry corruption, schema incompatibility, and lifecycle
  conflicts use `DATA`; and
- a later external cleanup provider may use `EXTERNAL_SERVICE`.

SQLite constraint and operational errors are translated into stable,
secret-safe project errors. Raw SQL, environment values, and unredacted
provider exceptions are not displayed or persisted. Lock contention receives
bounded retry behavior and actionable guidance rather than an indefinite
wait.

Declining confirmation changes nothing, prints `Removal cancelled`, and
returns `SUCCESS`. Scripts that require cleanup use `--force` and receive a
nonzero result for any incomplete provider. A provider failure never deletes
the registry record or marks that provider complete.

## Testing Strategy

### Unit coverage

- Git-root resolution from root, nested, symlinked, spaced, and Unicode paths;
- non-Git paths, bare repositories, missing Git, and malformed command output;
- platform layout mapping on macOS and Ubuntu;
- schema creation, supported migration, newer-schema rejection, constraints,
  rollback, and typed record conversion;
- multiple independent projects and idempotent registration;
- initializing-state recovery and lifecycle conflict handling;
- missing, moved, renamed, aliased, and path-reused repositories;
- relocation collision checks and identity refresh;
- dry-run immutability and exact resource descriptions;
- provider ordering, failure aggregation, progress persistence, skip-completed
  behavior, and retry;
- absent owned resources and provider-set reconciliation;
- unsafe parent, malformed UUID path, and symlink substitution rejection; and
- confirmation, `--force`, selector, and exit-code behavior.

### Integration and CLI coverage

Tests create real temporary Git working trees and isolated application homes.
They exercise:

- current-directory and explicit nested-path initialization;
- repeated initialization returning the same UUID;
- independent registration and allocation for multiple repositories;
- listing and status for available and missing paths;
- relocation after a real filesystem move;
- refusal when another repository reuses the old path;
- dry-run output with no mutations;
- declined, forced, failed, resumed, and successful removal; and
- preservation of source files and user-authored `.repo-intel.toml`.

Injected failing providers cover recovery without requiring a real external
service. Tests never use the developer's real registry or project data.

### Cross-platform acceptance gate

The complete quality gate and Module 3 lifecycle acceptance run on both
`macos-latest` and `ubuntu-latest`. The acceptance scenario uses temporary
real Git repositories and isolated platform roots to register, list, inspect,
move, detect path reuse, preview cleanup, recover an interrupted provider, and
verify exact final cleanup.

The gate verifies that:

- only UUID-scoped generated resources are deleted;
- source and repository configuration are unchanged;
- the registry contains no completed registration;
- unrelated registered projects remain intact; and
- the same scenario behaves consistently on macOS and Ubuntu.

Model downloads and Qdrant are outside this Module 3 gate because no
per-project embedding or vector resources exist yet.

## Completion Criteria

Module 3 is complete when:

1. every public command contract above is implemented and documented;
2. multiple repositories remain isolated;
3. registration is idempotent for the same canonical repository;
4. moved, missing, reused, and partially removed projects are recoverable;
5. dry run lists exact resources without mutation;
6. confirmed cleanup removes only `repo_intel`-owned resources;
7. source files and user-authored configuration remain untouched;
8. unit, integration, CLI, and acceptance tests pass;
9. the complete CI matrix passes on macOS and Ubuntu; and
10. the living execution plan records the exact completion evidence.
