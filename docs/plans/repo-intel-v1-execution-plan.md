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
| 1 | Project foundation and contracts | Complete | `docs/plans/module-01-foundation-implementation.md` |
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
| 2026-10-01 | 1 | Planned | In progress | User approved native execution on the main checkout | Module 2 remains gated until Module 1 passes both platform CI jobs |
| 2026-10-01 | 1 | In progress | Complete | Local gate passed and GitHub Actions passed on macOS and Ubuntu | Module 2 is authorized to enter planning |

## Module Completion Record

Add one entry when a module gate closes. Include the commit, commands executed,
platform evidence, benchmark evidence when applicable, known limitations, and
the next module authorized to enter planning.

### Module 1 — Local implementation checkpoint

- Commits: `3b5f4c2`, `1c03161`, `90a4672`, `8764caf`, `200e1d1`, `1cbc3ef`,
  `aee0165`
- Local platform: macOS, Python 3.12.14, uv 0.12.21
- Local checks: Ruff lint passed; Ruff format passed; strict MyPy passed for
  24 source files; Pytest passed 65 tests; source and wheel builds passed;
  console help, version, and module-entry smoke commands passed.
- Cross-platform evidence: [GitHub Actions run 36864796238](https://github.com/pain459/repo_intel/actions/runs/36864796238)
  passed `Quality (ubuntu-latest)` and `Quality (macos-latest)` with every
  workflow step successful.
- Status: `Complete`.
- Known limitation: Module 1 defines foundation contracts only; setup,
  diagnostics, repository registration, and indexing are intentionally absent.
- Next module: Module 2 is authorized to enter planning.
