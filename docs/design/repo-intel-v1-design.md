# repo_intel v1 Design

**Status:** Approved design reference

**Date:** 2026-10-01

**Scope:** First usable local release for macOS and Ubuntu

## 1. Purpose

`repo_intel` is a local repository knowledge and navigation engine for coding
agents. It indexes a local repository and returns a compact, evidence-backed
context package for an engineering task. It does not replace authoritative
source reads, the coding agent, or the developer's normal workflow.

The first release must let a user clone `repo_intel`, set it up locally,
register and index a Python repository, search it, obtain structured context
through the CLI or MCP, update the index incrementally, and remove all
generated data for that repository.

The central rule is:

> Give the model the smallest high-quality evidence set required to understand
> the task, not the repository itself.

## 2. Approved Product Constraints

- The implementation language is Python 3.12 or newer.
- `uv` is the required bootstrap dependency.
- macOS and Ubuntu are supported from the first release.
- Other Linux distributions are out of scope for release testing and may be
  supported later through additional platform adapters.
- Platform behavior must use detection and PATH lookup rather than hardcoded
  Homebrew or Linux executable paths.
- Python is the only language with structural parsing in v1.
- Other eligible text files may participate in scanning, lexical search, and
  documentation or configuration retrieval.
- Operation is local-first. Repository content, embeddings, metadata, and
  generated context remain local.
- `nomic-embed-text` is the required embedding model.
- Qwen coding models are recommended according to detected hardware but are
  not required for deterministic v1 indexing and context composition.
- Large model downloads, system-software installation, service startup, and
  OpenCode configuration changes require explicit user confirmation.
- Qdrant runs as a pinned Docker Compose service.
- Generated repository data lives in the platform user-data directory, not
  inside the source repository.
- Source code remains authoritative. Search and context results must retain
  source location and hash provenance.
- Cross-repository reasoning, Git-history intelligence, deep semantic call
  graphs, blast-radius analysis, engineering memory, and visualization are
  deferred beyond v1.

## 3. User Experience

The documented setup path is:

```bash
git clone <repo-intel-url>
cd repo_intel
uv sync
uv run repo-intel setup
```

The expected project workflow is:

```bash
repo-intel doctor
repo-intel init /path/to/python-project
repo-intel projects
repo-intel projects relocate <repository-id> /new/path/to/python-project
repo-intel index /path/to/python-project
repo-intel status /path/to/python-project
repo-intel search /path/to/python-project "token refresh"
repo-intel context /path/to/python-project "change token refresh retry behavior"
repo-intel mcp
repo-intel update /path/to/python-project
repo-intel remove /path/to/python-project --dry-run
repo-intel remove /path/to/python-project
```

These command forms are the public v1 CLI contract. Additional options may be
added in the execution plan, but the documented commands and their safety
properties must remain available.

## 4. System Boundaries

### `repo_intel` owns

- platform-aware setup and diagnostics
- project registration and lifecycle cleanup
- repository scanning and file classification
- Python parsing and structural chunking
- SQLite metadata, index state, and FTS5 search
- Ollama embedding requests
- Qdrant vector lifecycle and similarity search
- hybrid retrieval, ranking, deduplication, and token budgeting
- structured context composition
- incremental index updates
- local MCP exposure
- optional, confirmed OpenCode configuration integration

### External systems own

- Ollama: local model serving and embedding generation
- Qdrant: vector storage and similarity search
- Docker: Qdrant process and container lifecycle
- Git: repository status and tracked/ignored file information
- ripgrep: exact live-source search
- OpenCode: developer interaction, coding-agent orchestration, authoritative
  source reads, source modifications, and shell execution

## 5. Platform and Installation Design

The platform layer must provide a stable internal interface for:

- operating-system and architecture detection
- executable discovery through PATH
- user configuration, data, cache, and log directories
- memory, CPU, and accelerator inspection where reliably available
- platform-specific installation guidance
- service-health diagnostics

The macOS user-data location is under `~/Library/Application Support`, and
Ubuntu uses the XDG data directory, defaulting to `~/.local/share`. Paths must
be resolved through platform APIs and environment conventions rather than
concatenated from assumptions.

After `uv sync` creates the Python environment, `repo-intel setup` creates the
application configuration and manages the pinned Qdrant Docker Compose
service. It detects missing system dependencies and provides platform-specific
guidance. It must obtain confirmation before:

- installing system software
- pulling `nomic-embed-text`
- pulling a Qwen model
- starting Docker or Qdrant
- changing OpenCode configuration

Setup is idempotent and safe to cancel. `repo-intel doctor` is read-only.

Configuration precedence, from highest to lowest, is CLI option, documented
`REPO_INTEL_` environment variable, repository `.repo-intel.toml`, user
configuration, and built-in default. User configuration resides under the
platform configuration directory; generated index data remains under the
platform data directory.

## 6. Model Policy

`nomic-embed-text` is required for semantic indexing. The system checks its
availability and offers a confirmed pull when missing.

Setup inspects available RAM, processor architecture, and accelerator details
where the platform exposes them reliably. The initial recommendation tiers
are:

- `qwen2.5-coder:1.5b` for machines with less than 16 GiB of memory
- `qwen2.5-coder:7b` for machines with 16 through 47 GiB of memory
- `qwen3-coder:30b` for machines with at least 48 GiB of memory and a supported
  accelerator

If hardware inspection is incomplete, the recommendation must state its
uncertainty and fall back conservatively. A recommendation never initiates a
model download without confirmation.

V1 retrieval and context composition remain deterministic and do not require
a Qwen model. This prevents coding-model capacity from becoming an indexing
or search prerequisite.

## 7. Repository Data and Lifecycle

Each registered repository receives a generated UUID and an isolated user-data
allocation. The registry enforces canonical-path uniqueness and maps the UUID
to the canonical path and lifecycle state. When a repository moves,
`repo-intel projects relocate <repository-id> <new-path>` updates that mapping
after verifying the destination is a Git repository and is not already owned
by another registration.

Generated data includes:

- SQLite metadata and FTS state
- cached scan and parser state
- logs and operation checkpoints
- Qdrant vector ownership

Generated data does not live in the source repository. A repository may have
an explicitly requested `.repo-intel.toml`; cleanup must never delete this or
any other user-authored source file.

Lifecycle commands include project listing, status, dry-run removal, confirmed
interactive removal, and forced removal for scripts. Cleanup is provider-based
so later stores participate without changing the command contract. Removal is
idempotent and recoverable after partial failure.

## 8. Indexing Data Flow

```text
repository path
    -> Git-aware scanner
    -> file classification and secret exclusion
    -> SQLite inventory and index state
    -> Python parser and structural chunks
    -> FTS5 lexical index
    -> Ollama embeddings
    -> Qdrant vectors
    -> current index checkpoint
```

No failed or interrupted build may be advertised as current. Each result must
retain enough provenance to map to the authoritative repository, file, source
hash, symbol, and line range.

## 9. Retrieval Data Flow

```text
query
    -> lexical search
    -> live exact search
    -> semantic search
    -> symbol and structural lookup
    -> reciprocal-rank fusion
    -> deduplication
    -> token budgeting
    -> structured context package
```

Semantic infrastructure failure produces a clearly labelled degraded result
using the available lexical and structural evidence. It must not make lexical
search unavailable.

The v1 context package contains:

- task interpretation
- primary implementation candidates
- related symbols and files
- known imports and dependents
- relevant tests
- relevant configuration
- evidence locations and retrieval-signal explanations

Every excerpt links to current authoritative source metadata. Retrieval does
not claim a fully semantic call graph in v1.

The default context budget is 10,000 estimated model tokens. A user may set a
different positive budget through normal configuration precedence, and the
composer must always report the applied budget and estimated usage.

## 10. Security and Failure Handling

Sensitive files, including environment files, private keys, credentials,
certificates, and token-bearing files, are excluded from embedding, FTS
content, diagnostic output, and logs by default.

Repository symlinks must not allow scanning outside the repository root.
Remote MCP exposure and network listeners are disabled by default. Repository
selection is explicit, and one repository's results must never leak into
another's query.

Failures use stable error categories, actionable messages, and nonzero CLI
exit codes. External-service failures distinguish missing executables, stopped
services, unavailable models, timeouts, incompatible versions, and malformed
responses. Logs redact sensitive values.

## 11. Testing and Benchmarking

The project uses:

- Pytest for unit, integration, and end-to-end tests
- Ruff for linting and formatting checks
- MyPy for static type checking
- macOS and Ubuntu CI jobs
- version-controlled fixture repositories
- a fixed retrieval benchmark corpus with known answers

The initial release benchmark requires the correct primary file in the top
five for every release-gating query and at rank one for at least 80 percent of
those queries. Benchmark output records top-rank accuracy, top-five recall,
irrelevant-result count, token use, indexing duration, incremental update
duration, and query latency.

Each performance-sensitive module records a macOS and Ubuntu baseline against
the committed small and medium fixture repositories before its gate closes.
After a baseline is committed, a regression greater than 20 percent fails the
gate unless the execution-plan decision log records and justifies the change.

## 12. Living-Plan Governance

The design document records approved product and architectural decisions. The
execution plan records ordered work, exact files and interfaces, tests,
acceptance commands, status, and module-level gates.

The execution plan contains a change log with:

- date
- affected module
- previous decision
- revised decision
- reason
- downstream impact

When implementation changes a future module, the plan is updated immediately.
When a change invalidates completed behavior, the affected module reopens and
must pass its revised gate before later modules proceed.

Every module uses this completion contract:

1. Documented deliverables exist.
2. Unit and integration tests pass.
3. The user-facing acceptance scenario passes.
4. Platform-sensitive behavior is covered on macOS and Ubuntu.
5. Failure output is actionable and secret-safe.
6. Documentation describes actual behavior.
7. No unresolved issue blocks the next module.
8. Status and decisions are current in the execution plan.

## 13. Module Design and Gates

### Module 1: Project foundation and contracts

#### Deliverables

- Python 3.12+ package managed by `uv`
- Typer CLI with version and help commands
- typed configuration models and precedence rules
- macOS and Ubuntu platform abstraction
- logging, error categories, and exit-code conventions
- unit, integration, platform, and CI test structure
- interfaces for scanner, stores, parsers, embedders, retrievers, and context
  composition without speculative implementation

#### Success criteria

- A fresh clone completes `uv sync`.
- Help and version commands succeed.
- Tests, Ruff, and MyPy pass on macOS and Ubuntu.
- Package import does not require Ollama, Docker, or Qdrant to be running.
- Configuration and error behavior are tested.
- No unused external service or premature implementation is introduced.

### Module 2: Setup, diagnostics, and model recommendation

#### Deliverables

- `repo-intel setup` and `repo-intel doctor`
- PATH-based dependency discovery
- Git, ripgrep, Ollama, Docker-daemon, Qdrant, and model checks
- pinned Qdrant Docker Compose service and health check
- macOS and Ubuntu installation guidance
- confirmed `nomic-embed-text` setup
- hardware-aware Qwen recommendations
- confirmed model pulls and service startup
- idempotent setup and secret-safe diagnostics

#### Success criteria

- Doctor distinguishes installed, missing, stopped, and unhealthy dependencies.
- Setup works from a fresh clone on tested macOS and Ubuntu environments.
- Declined downloads or startup actions exit cleanly with useful guidance.
- Re-running setup creates no unintended changes.
- Recommendations degrade safely when hardware information is incomplete.
- Tests cover spaces in paths, missing PATH entries, stopped daemons, offline
  failures, and unsupported platforms.

### Module 3: Project registry, storage locations, and cleanup

#### Deliverables

- user-level project registry keyed by stable repository ID
- platform-native data locations
- `init`, `projects`, `projects relocate`, `status`, and `remove` commands
- removal dry run, confirmation, and scripted force mode
- cleanup-provider interface for current and future stores
- recovery for moved, missing, or partially deleted repositories

#### Success criteria

- Multiple repositories register independently.
- Re-registering the same canonical repository is idempotent.
- Dry run lists exact generated resources without deleting them.
- Removal deletes only `repo_intel`-owned data.
- Source and user-authored repository configuration remain untouched.
- Partial cleanup can be safely rerun.
- Tests cover symlinks, missing or renamed repositories, path reuse, and
  interrupted cleanup.

### Module 4: Repository scanner and file classification

#### Deliverables

- Git-aware root detection and discovery
- tracked files plus eligible untracked files
- `.gitignore`, `.repo-intel.toml`, and built-in exclusion support
- source, test, documentation, configuration, migration, generated, binary,
  sensitive, oversized, and ignored classifications
- content hashes and scan metadata
- deterministic inventory output

#### Success criteria

- An unchanged repository produces the same inventory and hashes.
- Exclusion and classification policies are enforced.
- Sensitive content never appears in logs, diagnostics, or fixtures.
- Symlinks cannot escape the repository root.
- Spaces, Unicode, unreadable files, nested ignore rules, and repositories
  without commits are covered.
- Fixture repositories produce exact inventories on macOS and Ubuntu.
- Representative scan time is measured and documented.

### Module 5: SQLite metadata and index state

#### Deliverables

- versioned schema and forward migrations
- repository, file, scan, hash, parser-version, model-version, and state records
- transactional inventory replacement
- stale-record removal
- WAL-mode connection lifecycle
- enforced repository isolation
- diagnosable index status

#### Success criteria

- Persisted inventories reconstruct without loss.
- Failed writes roll back completely.
- Unchanged rescans create no duplicates.
- Deletes and renames update state correctly.
- Supported schema upgrades preserve data.
- Concurrent readers never see a half-written update.
- Foreign-key, migration, rollback, and isolation tests pass.
- Corruption and unsupported versions return actionable errors.

### Module 6: Python parsing and structural chunks

#### Deliverables

- Tree-sitter Python parser
- modules, classes, functions, async functions, methods, imports, constants,
  decorators, and test definitions
- containment and import relationships
- syntax-aware function, method, class, module, and test chunks
- path, symbol, kind, line, parent, import, hash, and commit metadata
- stable identifiers for unchanged symbols and chunks
- graceful handling of invalid Python syntax
- explicit differentiation between syntax extraction and resolved semantics

#### Success criteria

- Golden fixtures produce exact symbols, relationships, and boundaries.
- Async code, decorators, nesting, multiline signatures, annotations, imports,
  tests, and empty modules are covered.
- Chunk line ranges map exactly to authoritative source.
- One invalid file does not abort repository indexing.
- Unchanged source retains stable identifiers.
- Source edits invalidate only affected structural records.
- Parser-version changes mark applicable files for reprocessing.
- Parser performance and memory usage are measured.

### Module 7: Lexical indexing and exact search

#### Deliverables

- SQLite FTS5 over eligible chunks, documentation, and configuration
- live exact search through ripgrep
- symbol, path, error, route, configuration-key, and text queries
- code-safe query normalization
- ranked, traceable results
- `search` and `symbol` CLI commands
- clear indexed-search and live-search semantics

#### Success criteria

- Exact fixture queries return authoritative locations.
- Changed or deleted content cannot remain after a successful update.
- Lines and hashes match current source.
- Code punctuation, dotted names, snake case, quotes, and empty queries are
  handled safely.
- Excluded and sensitive content is never returned.
- Identical state produces deterministic ranking.
- Small and medium repository performance is measured.
- Lexical search works without Ollama or Qdrant.

### Module 8: Ollama embeddings and Qdrant semantic search

#### Deliverables

- Ollama health, timeout, retry, and error handling
- `nomic-embed-text` validation
- batched embedding pipeline
- Qdrant collection and version management with repository/model isolation
- deterministic vector IDs and source-hash payloads
- incremental vector upsert and deletion
- semantic CLI search
- explicit degraded mode

#### Success criteria

- Paraphrase queries find relevant code without exact terms.
- Unchanged chunks are not re-embedded.
- Changed and deleted chunks leave no stale vectors.
- Incompatible models or dimensions cannot mix silently.
- Interrupted batches resume safely.
- Excluded and sensitive chunks never enter Qdrant.
- External failures produce actionable diagnostics.
- Repository cleanup removes every owned vector.
- Batch counts and performance agree with persisted state.

### Module 9: Hybrid retrieval and context composition

#### Deliverables

- parallel lexical, exact, semantic, symbol, containment, and import retrieval
- Reciprocal Rank Fusion
- authoritative-source and line-overlap deduplication
- signal explanations
- configurable token budgeting
- structured `context` output
- deterministic operation without a Qwen dependency

#### Success criteria

- Every release query returns its primary file in the top five; at least 80
  percent return it first.
- Context excludes sensitive files and other repositories.
- Every excerpt has current path, line, symbol, and hash provenance.
- Duplicate overlaps do not consume budget repeatedly.
- Output stays within its configured token budget.
- Semantic failure falls back to labelled lexical/structural output.
- Unchanged state produces stable output.
- Accuracy, recall, irrelevant results, tokens, and latency are recorded.

### Module 10: Incremental indexing and update orchestration

#### Deliverables

- initial `index` and subsequent `update` workflows
- hash, Git HEAD, dirty-state, parser, model, and schema change detection
- targeted stale-data removal and rebuilding
- durable phase checkpoints
- safe writer locking
- current, stale, incomplete, and incompatible status reporting
- explicit full rebuild option

#### Success criteria

- Unchanged update performs no parsing or embedding work.
- One independent file change touches only that file and affected records.
- Adds, deletes, renames, staged, unstaged, and eligible untracked files work.
- Interrupted updates never appear current.
- Concurrent writers fail safely.
- Version changes produce the documented minimum invalidation.
- Incremental output equals a clean rebuild of the same source state.
- A one-file update is at least five times faster than a full rebuild on the
  committed incremental-index benchmark fixture.

### Module 11: MCP and optional OpenCode integration

#### Deliverables

- local stdio MCP server
- `repo_context`, `repo_search`, `repo_symbol`, and `repo_status` tools
- typed, versioned tool schemas
- explicit, isolated repository selection
- previewed and confirmed OpenCode configuration merge
- Qwen recommendation in setup/configuration guidance
- authoritative-source-read instruction in context output
- no remote listener by default

#### Success criteria

- A clean OpenCode session can call `repo_context` for a registered Python
  repository.
- MCP and CLI results agree for the same query and state.
- Invalid projects, stale indexes, unavailable services, and malformed input
  return structured errors.
- Existing OpenCode configuration is preserved during merge.
- Declined configuration changes touch no user files.
- MCP startup does not rebuild unexpectedly.
- An end-to-end fixture returns primary code, related files, tests, and config.
- A tool cannot query an unselected repository.

### Module 12: End-to-end hardening and first release

#### Deliverables

- release validation of the pinned Qdrant Docker Compose service and health
  check delivered by Module 2
- clone-to-use macOS and Ubuntu documentation
- PATH, Ollama, model, Docker, Qdrant, permission, and cleanup troubleshooting
- configuration reference and migration policy
- reproducible benchmark command and corpus
- security review
- complete lifecycle acceptance suite
- changelog and explicit limitations

#### Success criteria

- A clean macOS and Ubuntu user can clone, sync, set up, diagnose, register,
  index, search, request context, connect MCP, update, and clean up by following
  documented steps.
- Tests, lint, typing, security checks, benchmarks, and platform jobs pass.
- Retrieval thresholds remain satisfied.
- Fixtures and logs contain no secrets.
- Installation and complete project-data removal are documented and tested.
- The workflow requires no undocumented manual repair.
- Deferred features are tracked rather than partially implemented.

## 14. Deferred Work

The following items require later design and module plans:

- JavaScript, TypeScript, and other structural parsers
- Git commit, diff, and co-change intelligence
- deeper reference and call resolution
- test-to-implementation mapping beyond syntax and imports
- blast-radius analysis
- persistent engineering memory
- cross-repository retrieval and impact analysis
- architecture inference and visualization
- support and CI coverage for additional Linux distributions

## 15. V1 Completion Definition

V1 is complete only when a new user on a clean supported machine can follow the
documented workflow from clone through safe cleanup, and when the fixed
benchmark and platform test matrices pass. A feature being implemented does
not make its module complete; its entire module gate must pass and its status
must be recorded in the living execution plan.
