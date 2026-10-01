# repo_intel v1 Execution Plan

**Design:** `docs/design/repo-intel-v1-design.md`

**Purpose:** This is the living delivery index for the twelve gated v1 modules.
Detailed task instructions live in one implementation plan per module so each
module can be reviewed, executed, and reopened independently.

## Status Values

- `Not planned`: design gate exists, but no task-level plan has been approved.
- `Planned`: task-level plan exists and is awaiting execution.
- `In progress`: implementation has started, but the module gate is open.
- `Blocked`: an unresolved dependency prevents safe progress.
- `Complete`: every design criterion and module acceptance check passes.
- `Reopened`: a later decision invalidated previously completed behavior.

## Module Status

| Module | Name | Status | Detailed plan |
|---:|---|---|---|
| 1 | Project foundation and contracts | In progress | `docs/plans/module-01-foundation-implementation.md` |
| 2 | Setup, diagnostics, and model recommendation | Not planned | — |
| 3 | Project registry, storage locations, and cleanup | Not planned | — |
| 4 | Repository scanner and file classification | Not planned | — |
| 5 | SQLite metadata and index state | Not planned | — |
| 6 | Python parsing and structural chunks | Not planned | — |
| 7 | Lexical indexing and exact search | Not planned | — |
| 8 | Ollama embeddings and Qdrant semantic search | Not planned | — |
| 9 | Hybrid retrieval and context composition | Not planned | — |
| 10 | Incremental indexing and update orchestration | Not planned | — |
| 11 | MCP and optional OpenCode integration | Not planned | — |
| 12 | End-to-end hardening and first release | Not planned | — |

## Progression Rule

Only one module may be `In progress`. Work on the next module begins only
after the current module is `Complete`. A module becomes `Complete` only when
all deliverables, automated checks, user-facing acceptance commands, platform
checks, documentation, and decision records required by its design gate pass.

If a decision changes completed behavior, mark the affected module `Reopened`,
record the change below, revise its detailed plan, and pass the revised gate
before continuing.

## Change Log

| Date | Module | Previous decision | Revised decision | Reason | Downstream impact |
|---|---:|---|---|---|---|
| 2026-10-01 | All | No task-level execution index | Adopt one living index plus one detailed plan per module | Keep the reference current without creating one unreviewable plan | Every module must link its approved detailed plan before implementation |

## Module Completion Record

Add one entry when a module gate closes. Include the commit, commands executed,
platform evidence, benchmark evidence when applicable, known limitations, and
the next module authorized to enter planning.
