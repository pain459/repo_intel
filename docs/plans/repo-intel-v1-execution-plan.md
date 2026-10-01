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
| 2 | Setup, diagnostics, and model recommendation | Complete | `docs/plans/module-02-setup-diagnostics-implementation.md` |
| 3 | Project registry, storage locations, and cleanup | In progress | `docs/plans/module-03-project-lifecycle-implementation.md` |
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
| 2026-10-01 | 1 | Complete | Reopened | Final review restored accidentally removed ignore rules and rejected relative XDG roots | Module 2 is gated until CI passes the reviewed Module 1 HEAD |
| 2026-10-01 | 1 | Reopened | Complete | Reviewed HEAD passed the complete GitHub Actions matrix on macOS and Ubuntu | Module 2 is authorized to enter planning |
| 2026-10-01 | 2 | Not planned | Planned | Approved v1 design was expanded into a task-level Module 2 plan | Implementation awaits plan review |
| 2026-10-01 | 2 | Planned | In progress | User approved native execution of the reviewed task-level plan | Module 3 remains gated until Module 2 passes its complete local and cross-platform gate |
| 2026-10-01 | 2 | Treat only decoded JSON as a healthy Qdrant probe | Accept the documented 2xx plain-text `/healthz` response for the fixed Qdrant endpoint | Whole-module review found that the JSON-only adapter otherwise marked a real healthy Qdrant service unhealthy | Regression coverage and the complete local gate now pass; remote CI must evaluate the reviewed HEAD |
| 2026-10-01 | 2 | Fake-backed acceptance plus manual commands were sufficient for the local gate | Require one separately confirmed real-machine runner covering actual model pulls and managed Qdrant startup | The user requested an end-to-end test of the delivered Modules 1 and 2 using real host services | Module 2 remains in progress until the live runner and exact pushed CI matrix pass |
| 2026-10-01 | 2 | In progress | Complete | The real-machine runner passed on macOS and the exact pushed acceptance-runner commit passed both GitHub Actions matrix jobs | Module 3 is authorized to enter planning |
| 2026-10-01 | 3 | Not planned | Planned | The approved project-lifecycle spec was expanded into a task-level implementation plan | Implementation awaits plan review and execution-method approval |
| 2026-10-01 | 3 | Planned | In progress | User approved native execution of the reviewed Module 3 plan on the main checkout | Module 4 remains gated until the exact reviewed commit passes local acceptance and both CI matrix jobs |

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
- Status at this checkpoint: `Complete` for commit `c4b6852`; superseded by
  the final-review correction below.
- Known limitation: Module 1 defines foundation contracts only; setup,
  diagnostics, repository registration, and indexing are intentionally absent.
- Next module at this checkpoint: Module 2 was authorized to enter planning.

### Module 1 — Final-review correction checkpoint

- Review-fix commit: `2baa134`
- Corrections: restored the repository's pre-existing Python ignore rules and
  made Ubuntu ignore relative `XDG_*_HOME` overrides so generated state cannot
  be placed beneath the working directory.
- Local checks: Ruff lint passed; Ruff format passed; strict MyPy passed for
  24 source files; Pytest passed 66 tests; source and wheel builds passed; Git
  whitespace validation and all three CLI smoke commands passed.
- Cross-platform evidence: [GitHub Actions run 36866220648](https://github.com/pain459/repo_intel/actions/runs/36866220648)
  passed `Quality (ubuntu-latest)` and `Quality (macos-latest)` for reviewed
  commit `a0ca39f`, including every workflow step.
- Status: `Complete`.
- Next module: Module 2 is authorized to enter planning.

### Module 2 — Completion record

- Commits: `c081528`, `0a7dd0b`, `b49de0e`, `ab7c030`, `92fd2ac`, and
  `e47333e`; Task 7 is `8377a67`; whole-module review correction is `fd1dd31`;
  real-machine acceptance support is `ba8103e`.
- Local platform: macOS, Python 3.12.14, uv 0.12.21.
- Local checks: locked dependency sync passed; Ruff lint passed; Ruff format
  passed; strict MyPy passed for 57 checked files; Pytest passed 173 tests;
  source and wheel builds passed; console help, setup help, doctor help,
  version, module-entry, real-acceptance help, package-resource, and Git
  whitespace checks passed.
- Acceptance coverage: fake-backed doctor and setup workflows exercise macOS
  and Ubuntu behavior without contacting local services, pulling models, or
  starting Docker. The GitHub Actions matrix runs those checks on both hosted
  platforms.
- Review: self-review of the complete Module 2 range found and corrected one
  Important Qdrant health-contract defect. A read-only production `doctor`
  smoke on macOS also returned categorized, secret-safe findings and the
  expected conservative hardware fallback under sandbox-restricted `sysctl`.
- Real-machine acceptance: `uv run python scripts/acceptance_modules_01_02.py`
  passed on the user's macOS host with Python 3.12.14. It passed the complete
  Module 1 gate, native macOS path checks, read-only diagnostics, safe
  non-interactive setup, the pinned localhost-only Compose contract, real
  `nomic-embed-text` and `qwen2.5-coder:7b` availability, managed Qdrant
  startup and health, container ownership checks, and an idempotent setup
  rerun. The final result was `ACCEPTANCE PASSED`.
- Cross-platform evidence: [GitHub Actions run 36874738799](https://github.com/pain459/repo_intel/actions/runs/36874738799)
  passed `Quality (ubuntu-latest)` and `Quality (macos-latest)` for exact
  commit `ba8103eb6e71353d548893aff7a47b598ca40cc5`, including all workflow
  steps.
- Status: `Complete`; the local quality gate, whole-module review,
  real-machine acceptance, and exact-commit macOS/Ubuntu CI gate all passed.
- Known limitations: system package installation remains guidance-only; Qwen
  is an optional recommendation; CI intentionally substitutes deterministic
  fakes for destructive or machine-specific service actions. The accepted
  Ollama models and managed Qdrant container/data intentionally remain on the
  user's machine.
- Next module: Module 3 is authorized to enter planning.

### Module 3 — Local implementation checkpoint

- Local platform: macOS, Python 3.12.14, uv 0.12.21.
- Local checks: locked dependency sync passed; Ruff lint passed; Ruff format
  passed for 76 files; strict MyPy passed for 76 checked source, test, and
  script files; Pytest passed 259 tests; source and wheel builds passed; all
  Module 3 CLI help surfaces, the module entry point, and Git whitespace
  validation passed.
- Acceptance: `uv run python scripts/acceptance_module_03.py` passed with real
  temporary Git repositories and isolated application roots. It covered
  idempotent init, independent registrations, listing/status, explicit
  relocation, path reuse, exact dry run, symlink refusal, independent-provider
  continuation, durable retry, final registry deletion, and preservation of
  source, `.repo-intel.toml`, replacement, sentinel, and unrelated state.
- Review: self-review of the complete Module 3 range found and corrected two
  Important issues: unsafe targets initially failed during planning before
  independent providers could run, and unexpected acceptance exceptions could
  bypass the redacted failure surface. The reviewed local gate has no remaining
  Critical or Important findings.
- Status: `In progress`; the reviewed Task 7 commit still requires the
  user-owned push and successful `Quality (macos-latest)` and
  `Quality (ubuntu-latest)` jobs for the exact commit.
- Known limitations: moved repositories require explicit relocation; automatic
  discovery, scanning, indexing, embeddings, Qdrant project data, and MCP are
  intentionally deferred to later modules.
- Next module: Module 4 remains gated until Module 3 remote CI closes.
