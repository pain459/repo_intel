# repo_intel — Architecture and Complete Implementation Plan

**Status:** Proposed implementation baseline (v1.0)  
**Target:** Single-developer MVP with a reusable MCP intelligence backend, designed for local and distributed deployments.  
**Primary client:** OpenCode CLI/Desktop.  
**Primary inference:** Ollama OpenAI-compatible chat endpoint; Ollama embedding endpoint.  
**Guiding principle:** The live working tree is authoritative; the index is derived and rebuildable; memory is evidence-linked and revocable.

---

## 1. Product definition and non-goals

repo_intel gives coding agents persistent, searchable knowledge of repositories, their dependency relationships, and verified task history. It improves retrieval and long-session continuity while respecting the model's finite context window.

### User-facing capabilities

1. Register a local Git repository and index its tracked source and documentation.
2. Search by exact identifiers, filenames, keywords, semantics, and code symbols.
3. Return compact, cited evidence packs with explicit token budgets.
4. Expose retrieval and memory tools through MCP to OpenCode.
5. Record evidence-backed decisions, task checkpoints, test results, and rejected approaches.
6. Refresh changed files incrementally, including uncommitted working-tree changes.
7. Recover relevant knowledge after OpenCode compaction or a new session.
8. Operate from one laptop, or use remote Ollama and/or a remotely hosted intelligence backend.

### Explicit non-goals for MVP

- No replacement for OpenCode's editor, shell, Git, or execution tools.
- No claims of literally unlimited LLM context.
- No automatic execution of retrieved instructions or arbitrary repository scripts.
- No Kubernetes, Redis, Kafka, separate vector database, or web dashboard requirement.
- No multi-user tenancy, remote filesystem write access, or automated Git pushes in v1.
- No compulsory SCIP indexer in the first usable release; start with Tree-sitter and optional language-specific enrichment.

### Acceptance definition

A new user can clone repo_intel, run one setup flow, register a repository, index it, configure an MCP client, retrieve code evidence, make an OpenCode edit, and verify that the index catches up to the edit. A fresh agent session can retrieve an evidence-backed checkpoint from a previous session.

---

## 2. Deployment topology

### Profile A: minimum supported installation

```text
One developer computer
├── OpenCode CLI/Desktop (native)
├── Working Git repository (native filesystem)
├── Optional native watcher/CLI
├── Docker Compose
│   ├── repo-intel-api (FastAPI + MCP + retrieval + memory)
│   ├── repo-intel-worker (same image; background jobs)
│   └── postgres (pgvector extension, durable volume)
└── Inference endpoint
    ├── Local Ollama, or
    └── Remote OpenAI-compatible coding model + embedding endpoint
```

The API and worker are **two processes using one image and codebase**, not two independently developed microservices. In the minimum setup, the watcher can be replaced by a polling scan, eliminating an extra native daemon. Use Docker bind mounts for registered repositories with read-only access. Only OpenCode edits files.

### Profile B: current Mac + Ubuntu deployment

```text
MacBook Pro                                      Ubuntu 192.168.68.62
├── OpenCode native                             └── Ollama :11434
├── Git repos                                       ├── qwen3.6:27b
├── repo-intel CLI + optional native watcher        └── embedding model
└── Docker Compose
    ├── repo-intel-api / MCP :8765
    ├── repo-intel-worker
    └── postgres + pgvector
               │
               └──── HTTP LAN requests to Ollama ──────>
```

OpenCode talks **directly** to Ollama for coding. OpenCode also connects to repo_intel via MCP. repo_intel calls Ollama independently for embeddings; it does not proxy every OpenCode model request. PostgreSQL stays on the Mac because the indexed repositories are local and because it minimizes deployment dependencies. Remote inference outages degrade new embeddings, not keyword search of already indexed content.

### Profile C: later team/centralized installation

A centrally hosted API and database can accept authenticated incremental updates from per-developer local agents. This requires authentication, isolation, transport security, and explicit sync semantics, and is **out of MVP scope**. Never mount a user's Mac repository on an untrusted remote server.

### Port and network contracts

| Port | Service | Exposure |
|---|---|---|
| 8765 (proposed) | repo_intel HTTP/MCP | Bind to `127.0.0.1` in single-user mode |
| 5432 | PostgreSQL | Docker internal only; no host publishing required |
| 11434 | Ollama | Existing local or LAN endpoint; no repo_intel proxy |

For remote inference, validate reachability, model existence, embedding dimension, timeouts, and streaming support in `repo-intel doctor`. Do not assume Ollama is present on the same host as Docker.

---

## 3. Technology decisions

| Layer | Selection | Reason / tradeoff |
|---|---|---|
| Language | Python 3.12+ | Strong parsing, retrieval, DB, and MCP ecosystem |
| API | FastAPI + Pydantic v2 | Typed HTTP contracts, validation, testability |
| MCP | Official Python MCP SDK | Standards-based tools over streamable HTTP or stdio adapter |
| Database | PostgreSQL 16+ with pgvector | SQL, FTS, vector retrieval, transactional memory |
| DB migrations | Alembic + SQLAlchemy 2 | Versioned schema changes |
| Parsing | Tree-sitter + supported grammars | Syntax-aware chunks; fall back to text for unsupported files |
| Symbol graph | Tree-sitter extraction first; SCIP optional | Avoid blocking MVP on language-specific SCIP toolchains |
| Embeddings | Ollama `/api/embed` adapter | Works with local or LAN inference; version/dimension tracked |
| Hybrid retrieval | Postgres FTS + pgvector + exact match | No additional search service |
| Fusion | Reciprocal rank fusion | Simple, explainable, tunable |
| Reranking | Optional later | Keep initial requirements and latency low |
| CLI | Typer | Easy `init`, `index`, `status`, `doctor`, `search` |
| File changes | Polling baseline; optional native watchdog | Portable and robust on Docker Desktop for Mac |
| Tests | pytest, httpx, testcontainers or Compose integration tests | Unit and real-service coverage |
| Packaging | uv or pinned pip requirements + Docker | Reproducible development and container builds |
| Observability | Structured JSON logs + Prometheus metrics | Debug retrieval and sync behavior |

**Embedding model:** choose a small embedding-capable Ollama model during setup (for example, `nomic-embed-text` if installed). Validate the actual vector dimension dynamically; never hardcode one model's dimension across all collections. A change in embedding model or dimension requires a separate index generation and re-embedding, not mixing incompatible vectors.

---

## 4. Repository layout

```text
repo_intel/
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── compose.yaml
├── compose.dev.yaml
├── Dockerfile
├── Makefile
├── scripts/
│   ├── install.sh
│   ├── verify.sh
│   └── backup.sh
├── config/
│   ├── default.yaml
│   └── profiles/
│       ├── local.yaml
│       └── remote-ollama.yaml
├── src/repo_intel/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── api/
│   │   ├── app.py
│   │   ├── health.py
│   │   ├── repositories.py
│   │   ├── search.py
│   │   └── memories.py
│   ├── mcp/
│   │   ├── server.py
│   │   ├── tools.py
│   │   └── transport.py
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py
│   │   └── migrations/
│   ├── ingest/
│   │   ├── discovery.py
│   │   ├── filtering.py
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   ├── symbols.py
│   │   ├── hashing.py
│   │   ├── embeddings.py
│   │   ├── jobs.py
│   │   └── watcher.py
│   ├── retrieval/
│   │   ├── exact.py
│   │   ├── lexical.py
│   │   ├── semantic.py
│   │   ├── fusion.py
│   │   ├── expansion.py
│   │   ├── context_pack.py
│   │   └── freshness.py
│   ├── memory/
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── checkpoints.py
│   │   └── validation.py
│   ├── providers/
│   │   ├── base.py
│   │   └── ollama.py
│   ├── security/
│   │   ├── paths.py
│   │   └── redaction.py
│   └── observability/
│       ├── logging.py
│       └── metrics.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── fixtures/
│   └── evaluation/
├── examples/
│   ├── sample-repo/
│   └── opencode-config.example.jsonc
└── docs/
    ├── architecture.md
    ├── deployment.md
    ├── mcp-contract.md
    ├── operations.md
    ├── security.md
    └── evaluation.md
```

All project-owned services, tooling, scripts, configuration, migrations, test fixtures, and documentation live inside `repo_intel`. No reliance on older projects or external hand-built infrastructure.

---

## 5. Data model and indexing semantics

### Tables

1. `repositories`: UUID, canonical host path (local-only), logical name, registration time, scan status, include/exclude configuration.
2. `index_generations`: UUID, repository ID, embedding model/version/dimension, parser version, creation time, state (`building`, `active`, `retired`, `failed`).
3. `files`: repository ID, normalized relative path, language, size, content SHA-256, Git HEAD, worktree dirty flag, last observed timestamp, deleted flag; unique `(repository_id, relative_path)`.
4. `chunks`: UUID, file ID, generation ID, start/end lines, chunk type, symbol name, content hash, content, token estimate, FTS `tsvector`, embedding vector, indexed timestamp. Use separate generation-specific embedding partitions/tables if dimensions vary.
5. `symbols`: UUID, file ID, name, fully qualified name if resolvable, kind, location, parser source, generation ID.
6. `symbol_edges`: from/to symbol IDs, relation (`imports`, `references`, `calls`, `defines`), evidence location, confidence. Do not pretend unresolved dynamic calls are exact.
7. `index_jobs`: UUID, repo ID, kind, status, attempts, lease owner/expiry, timestamps, error summary, dedupe key.
8. `memories`: UUID, repo ID, kind, statement, status (`candidate`, `verified`, `superseded`, `rejected`), evidence JSON, source commit/worktree hash, created/updated times, author/source, expiry/review time.
9. `task_checkpoints`: UUID, repo ID, session external ID, objective, current state, changed files, tests and results, pending steps, evidence, created time.
10. `retrieval_events`: UUID, request ID, repo ID, query, selected chunk IDs, index generation, stale count, token budget, elapsed time, created time. Avoid logging sensitive raw text by default.
11. `schema_version` is managed by Alembic, not manually.

### Invariants

- Relative paths must be normalized and confined to registered roots; reject path traversal and symlink escape.
- Exclude `.git`, `node_modules`, virtual environments, build output, secrets and binary files by default. Respect `.gitignore` and user overrides.
- Never execute indexed code or instructions.
- Index updates are atomic: publish a generation only after its required records are consistent.
- On file modification, mark affected chunks stale immediately and refresh them asynchronously.
- On deletion, tombstone the file and remove its chunks from active search.
- Include worktree SHA-256 or observed content hash in every retrieval result.
- The source file must be reread before OpenCode edits it; MCP results are evidence, not authoritative writable content.
- Persist embedding provider/model/dimension and chunker version for reproducibility.

### Chunking

- Parse code into function/class/method units where practical, with imports and enclosing context retained as metadata.
- Split oversized syntax nodes by logical blocks, with a modest overlap and stable IDs.
- Documentation uses heading-aware sections.
- Plain text fallback uses bounded token-aware chunks.
- Do not embed files over configured size limits without explicit opt-in.
- Deduplicate unchanged chunks by content hash within the same model/index generation.

---

## 6. Retrieval and context construction

### Pipeline

```text
User task / MCP tool call
    → repository scope resolution
    → exact filename / identifier candidates
    → PostgreSQL lexical FTS candidates
    → pgvector semantic candidates
    → reciprocal rank fusion
    → symbol-neighbor expansion (bounded)
    → freshness / permissions / dedupe filters
    → token-budgeted evidence pack
    → MCP response with citations + confidence limits
```

### Context-pack response contract (illustrative)

```json
{
  "repository_id": "<uuid>",
  "query": "Why can a receipt be missing after a successful payment?",
  "index_generation": "<uuid>",
  "index_status": "current",
  "token_budget": 12000,
  "estimated_tokens": 8450,
  "results": [
    {
      "path": "app/transactions/service.py",
      "start_line": 44,
      "end_line": 110,
      "content_hash": "sha256:...",
      "retrieval_methods": ["exact", "lexical", "semantic"],
      "relevance_reason": "Transaction commit and receipt scheduling",
      "text": "<bounded excerpt>"
    }
  ],
  "warnings": []
}
```

The MCP tool must return bounded excerpts, not megabytes of code. Results should prioritize precise paths/line ranges, include truncation markers, and explicitly warn when the index is stale or a language is unsupported. Do not fabricate numerical confidence probabilities.

### Proposed MCP tool surface

| Tool | Inputs | Output |
|---|---|---|
| `repo_list` | none | registered repositories and freshness |
| `repo_search` | repository, query, limit | ranked file/symbol/snippet hits |
| `repo_symbol` | repository, symbol | definitions and references where available |
| `repo_dependencies` | repository, symbol, depth | bounded, evidence-linked graph |
| `repo_context` | repository, task, token_budget | curated evidence pack |
| `memory_search` | repository, query, status filter | evidence-backed memories |
| `memory_record` | repository, kind, statement, evidence | candidate memory ID; verification policy |
| `task_checkpoint` | repository, objective, state, evidence | checkpoint ID |
| `task_resume` | repository, session/checkpoint ID | latest validated checkpoint + stale warnings |
| `index_status` | repository | generation, queued work, failures |

Keep initial tool descriptions concise and tool parameters strongly typed. A tool name is a proposal until implemented and contract-tested. No MCP tool gets shell execution or arbitrary write-to-repository capability.

### Compaction behavior

Phase 5 introduces an OpenCode-specific optional integration. On compaction or session transitions, persist a checkpoint of objective, completed actions, changed files, test outcomes, known errors, and next steps. Recovery retrieves only the most relevant verified memory and current file evidence. Since hooks and API details can change between OpenCode releases, validate against the installed version and retain a manual `task_checkpoint` / `task_resume` fallback. Never promise that MCP alone automatically triggers at compaction.

---

## 7. Configuration and installer contracts

### Proposed `.env` keys

```dotenv
REPO_INTEL_PROFILE=local
REPO_INTEL_HOST=127.0.0.1
REPO_INTEL_PORT=8765
DATABASE_URL=postgresql+psycopg://repo_intel:CHANGE_ME@postgres:5432/repo_intel
REPO_ROOTS=/workspace
OLLAMA_BASE_URL=http://host.docker.internal:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BATCH_SIZE=16
INDEX_POLL_SECONDS=10
MAX_FILE_BYTES=1048576
DEFAULT_CONTEXT_TOKENS=12000
LOG_LEVEL=INFO
```

For the Mac + Ubuntu profile, set `OLLAMA_BASE_URL=http://192.168.68.62:11434`. `REPO_ROOTS` refers to **container-visible** paths and is paired with explicit read-only Docker mounts. Avoid embedding passwords in committed files; installer writes a local, gitignored `.env` with restrictive permissions. Production secrets should use secret mounts or a secrets manager.

### Proposed Compose shape

```yaml
services:
  api:
    build: .
    command: ["repo-intel", "serve"]
    env_file: .env
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ${HOST_REPO_ROOT:?set HOST_REPO_ROOT}:/workspace:ro
    depends_on:
      postgres:
        condition: service_healthy
  worker:
    build: .
    command: ["repo-intel", "worker"]
    env_file: .env
    volumes:
      - ${HOST_REPO_ROOT:?set HOST_REPO_ROOT}:/workspace:ro
    depends_on:
      postgres:
        condition: service_healthy
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: repo_intel
      POSTGRES_USER: repo_intel
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U repo_intel -d repo_intel"]
      interval: 5s
      timeout: 3s
      retries: 20
volumes:
  pgdata:
```

This is a **design sketch**, not a ready-to-run stack. Before shipping: reconcile `DATABASE_URL` with the generated password, set container user permissions, add API/worker healthchecks, resource limits, graceful shutdown, migration startup ordering, and version-pinned image digests. For multiple unrelated repositories, installer must manage an allowlisted mount map rather than silently mount the whole home directory.

### CLI UX (to implement)

```bash
./scripts/install.sh
repo-intel doctor
repo-intel init /path/to/repository
repo-intel index /path/to/repository
repo-intel status
repo-intel search /path/to/repository "receipt generation"
repo-intel mcp configure --client opencode
repo-intel backup /path/to/backup
```

Installer checks Docker availability, Docker Compose, network/model reachability, embedding response dimension, DB migrations, file access, and MCP connectivity. It should support reruns without destructive changes, a `--dry-run` mode, and uninstall that preserves user data unless explicitly requested.

### OpenCode integration

OpenCode's exact MCP config syntax and lifecycle hooks must be checked against the user's installed OpenCode version before generating a config fragment. Provide an installer-generated fragment and merge it without overwriting existing providers or models. Prefer loopback HTTP MCP for the local stack; an optional stdio bridge can be supplied if client compatibility requires it. Never hardcode a provider schema based solely on examples from older releases.

---

## 8. Six implementation phases and gates

### Phase 1 — Foundation and deployment

**Goal:** A reproducible, healthy installation on one machine and on the Mac/Ubuntu split.

**Implement:** project skeleton, Python packaging, typed configuration, FastAPI app, Compose API/worker/Postgres, pgvector extension, Alembic migration baseline, health/readiness, structured logs, CLI commands (`doctor`, `status`), installer and environment templates, CI lint/type/test/build.

**Deliverables:** `docker compose up -d` works; database persists restart; `GET /health/live`, `GET /health/ready`, and CLI doctor report accurate status; remote Ollama is tested without tunneling; secrets excluded from Git.

**Exit gate:** Fresh clone setup succeeds on macOS; local inference and remote-Ollama profiles pass smoke tests; restart does not lose DB; intentional bad credentials and unavailable Ollama produce actionable errors.

**Not included:** embeddings, indexing, MCP, persistent task memory.

### Phase 2 — Repository ingestion and indexing

**Goal:** Create an accurate, incrementally refreshable repository index.

**Implement:** repository registration, path safety, gitignore filtering, source discovery, binary/size exclusion, Tree-sitter parsing, fallback chunking, symbol extraction, content hashing, index job queue with DB leases, embedding adapter, pgvector storage, polling scanner, incremental upsert/delete, index generations and failure recovery.

**Deliverables:** `init`, `index`, `status`; searchable tables populated; changes and deletions reflected; diagnostics for unsupported files and embedding outages.

**Exit gate:** Index a realistic sample repository; unchanged rerun causes no unnecessary re-embeddings; editing one file updates only affected chunks; deletion removes active results; symlink escape is rejected; model-dimension mismatch is handled safely.

**Not included:** complex call graph, autonomous memory writes.

### Phase 3 — Hybrid retrieval and MCP integration

**Goal:** OpenCode can retrieve correct, bounded code evidence using MCP.

**Implement:** exact/FTS/vector candidate search, reciprocal-rank fusion, deduplication, limited symbol-neighbor expansion, context pack budgeting, freshness checks, REST search endpoints, MCP server and tools, MCP contract tests, OpenCode configuration helper, example prompts/instructions.

**Deliverables:** `repo_search`, `repo_symbol`, `repo_context`, `index_status`; reproducible evaluation queries; one end-to-end OpenCode demonstration.

**Exit gate:** OpenCode can locate a definition, relevant callers, and related tests in a multi-file task; every result has path and line references; output stays under requested budget; stale content is flagged; MCP failure does not prevent normal OpenCode file operations.

**Not included:** compaction automation, claim of automatic tool invocation on every prompt.

### Phase 4 — Persistent evidence-backed memory

**Goal:** Carry decisions and verified task history across independent sessions.

**Implement:** memory schema and lifecycle, candidate/verified/superseded status, evidence validation, task checkpoints, memory search, memory APIs and MCP tools, contradiction handling, retention controls, repository scope, sensitive-content redaction.

**Deliverables:** `memory_search`, `memory_record`, `task_checkpoint`, `task_resume`; audit trail; explicit verify/supersede operations; documentation on what is safe to remember.

**Exit gate:** A decision created in session A is found in session B; outdated decisions are superseded; unsupported memory cannot silently become verified; checkpoint includes tests and changed files; repository A cannot retrieve repository B's scoped memory unintentionally.

**Not included:** OpenCode lifecycle hooks (next phase).

### Phase 5 — Context continuity and optional OpenCode hooks

**Goal:** Reduce information loss during long sessions and context compaction.

**Implement:** optional OpenCode plugin/lifecycle adapter, pre-compaction checkpoint if supported, session resume bootstrap, retrieval policy, token budgeting and observability, stale-checkpoint invalidation, graceful manual fallback, load-shedding and timeouts.

**Deliverables:** version-tested integration adapter, manual commands, context diagnostics, controlled long-task test suite.

**Exit gate:** A long task survives compaction and can resume with verified objective, files, tests, and next steps; prompt sizes stay within configured limits; failed hook does not corrupt the task or block coding; baseline OpenCode behavior remains usable when repo_intel is offline.

**Important:** Investigate actual installed OpenCode hook semantics before implementing; no fabricated lifecycle guarantees.

### Phase 6 — Hardening, evaluation and release

**Goal:** A safe, documented, reproducible MVP suitable for other developers.

**Implement:** benchmark suite, parser/embedding version migration strategy, DB backup/restore, clean uninstall, resource profiling, repository-scale tests, permission audit, secret scanning, prompt-injection defenses, user documentation, release packaging, compatibility matrix, CI release artifacts.

**Deliverables:** tagged v1.0 release, one-command installation, operational runbook, failure troubleshooting, example repositories, benchmark report, clear minimum system requirements derived from measurements.

**Exit gate:** Clean installation by a second user; backup/restore verification; no cross-repository leaks; retrieval quality improves over baseline keyword search on the evaluation set; bounded memory/CPU and context use; end-to-end workflow passes on both deployment profiles.

---

## 9. Evaluation methodology

### Baseline tasks

Build a labeled fixture repository with realistic modules, services, tests, architectural notes and Git history. Use at least these query classes:

1. Exact symbol definition and references.
2. Natural-language behavior-to-code search.
3. Cross-file root-cause analysis.
4. Related test discovery.
5. Rename and stale-index detection.
6. Uncommitted working-tree change visibility.
7. Memory retrieval after a new session.
8. Conflicting or superseded decision handling.
9. Prompt-injection text embedded in a source comment.
10. Offline embedding endpoint with fallback to lexical retrieval.

### Metrics

- Recall@5/10 for labeled relevant files/chunks.
- Mean reciprocal rank for primary target.
- Citation correctness: path exists, lines match, hash/revision valid.
- Index freshness lag p50/p95 after edits.
- Re-embedding count after no-op and one-file change.
- Retrieval latency p50/p95.
- Context pack estimated tokens versus configured budget.
- OpenCode task completion and tool-call schema success rate.
- Memory precision and stale-memory rejection rate.
- Container RSS/CPU/disk usage for small, medium and large repositories.

Set numeric performance targets after baseline measurements, not by inventing guarantees. Compare three conditions: OpenCode alone; OpenCode with lexical retrieval; OpenCode with full hybrid repo_intel retrieval.

---

## 10. Security, reliability, and data governance

- Bind single-user MCP/API to loopback by default; add auth/TLS before exposing it over a network.
- Treat repository text, Git messages, comments and retrieved memories as **untrusted data**, never instructions that override the user's task or system policy.
- Do not include `.env`, private keys, credentials, or ignored secret files in the index by default. Add secret scanning before embedding or storing snippets.
- Mount repositories read-only into containers; OpenCode remains responsible for writes.
- Enforce path normalization, allowlisted roots, symlink confinement and size caps.
- Record provenance and timestamps for all memories; no unverified autonomous promotion to verified state.
- Bound all tool output, graph traversal, timeouts, queue retries, and retrieval fanout.
- Use idempotent ingestion, transactional updates, and worker leases for crash recovery.
- Support backup and restore of PostgreSQL, plus deterministic reindexing of derived content.
- Provide deletion operations for repository indexes, session checkpoints, and memories.
- Never log credentials, full prompt bodies, or full source snippets by default.
- Warn users when using a remote embedding provider that code excerpts may leave the machine.

---

## 11. Detailed example: a missing receipt

**Scenario:** A payment transaction commits but a receipt sometimes does not appear.

1. The developer opens the payment repository in OpenCode on the Mac.
2. The developer asks: “Find why committed payments sometimes lack receipts. Fix and test it.”
3. OpenCode invokes `repo_context` with the registered repository and a 12,000-token budget.
4. repo_intel retrieves the transaction service, receipt worker, queue/outbox handling, related tests and any verified architectural decision. It returns excerpts with paths, line numbers and file hashes.
5. OpenCode passes that evidence to Qwen on Ubuntu using its existing Ollama provider connection.
6. Qwen proposes a hypothesis; OpenCode reads the **current** source files, executes targeted tests, and edits code using its own tools.
7. repo_intel notices changed files via polling or watcher notification and incrementally refreshes affected chunks.
8. Once tests pass, OpenCode records a checkpoint containing the task objective, changed files, exact test commands/results, and an evidence-backed decision.
9. In a later session, OpenCode can retrieve the checkpoint and verify it still applies to the current commit.
10. If the conversation compacts, the optional integration restores a concise validated checkpoint instead of replaying the full conversation.

**Failure behavior:** If the embedding model is unavailable, existing lexical search still works; if repo_intel is unavailable, OpenCode continues to read/edit/test normally; if the index is stale, tools flag it and OpenCode reads the live files directly.

---

## 12. Coding sequence inside each phase

For each phase, use the same development loop:

1. Freeze the phase's API/data contracts and create acceptance tests first.
2. Implement the smallest vertical slice end-to-end.
3. Run formatting, type checking, unit tests, integration tests and Compose smoke tests.
4. Exercise the Mac/Ubuntu remote-Ollama profile and the single-machine profile.
5. Capture evidence: commands, logs, test results, DB state, performance and limitations.
6. Update README, architecture decisions, migration notes and operator runbook.
7. Do not advance until exit gates pass; failed gates create focused repair work, not silent scope expansion.

### Recommended first coding task (Phase 1, PR 1)

- Create `pyproject.toml`, package entry point, typed settings, FastAPI application, `/health/live`, and pytest coverage.
- Create Dockerfile and Compose file with API, worker placeholder, PostgreSQL/pgvector, and named volume.
- Add Alembic initialization and first migration.
- Add `repo-intel doctor` with database and Ollama checks, including remote URL support.
- Add `.env.example`, `scripts/install.sh` with preflight checks, and `scripts/verify.sh`.
- Document `docker compose up -d --build` and expected health outputs.
- **Do not** implement indexing, retrieval, or memory in PR 1.

---

## 13. Open decisions to validate early

1. **MCP transport:** streamable HTTP preferred, but confirm installed OpenCode support and exact config keys.
2. **Embedding model:** select an installed model, verify actual dimensions and performance on source code; make provider pluggable.
3. **Repo mount policy:** one repository per installation initially versus allowlisted multiple roots; design registry for multiple repositories regardless.
4. **Native watcher:** ship polling first; optional native watcher if latency demands it.
5. **Index generation storage:** use separate vector tables or generation partitions to accommodate different dimensions; choose before Phase 2 migration.
6. **Language scope:** Python, TypeScript/JavaScript, Go initially; C++ grammar support next, with plain-text fallback for all others.
7. **Tool-call reliability:** test Qwen's MCP tool calls and fallback to explicit CLI search when malformed calls occur.
8. **Retention:** default memory and retrieval event retention must be configurable and documented.

These are implementation decisions, not reasons to postpone the foundation. Record final choices in `docs/architecture.md` and architecture decision records before dependent migrations.

---

## 14. Definition of v1.0 done

- [ ] Fresh install on one supported developer machine succeeds.
- [ ] Mac + Ubuntu Ollama split works without tunnel or proxy.
- [ ] PostgreSQL persists and restores correctly.
- [ ] Repo registration/indexing works with incremental changes and deletes.
- [ ] Hybrid retrieval returns bounded, correctly cited evidence.
- [ ] OpenCode can invoke MCP tools without overwriting existing model configuration.
- [ ] Cross-session checkpoint and memory retrieval works.
- [ ] Compaction continuity works where hooks are supported, with manual fallback.
- [ ] Unsupported, stale and conflicting evidence is clearly labeled.
- [ ] Security tests cover path traversal, secrets and prompt injection.
- [ ] Evaluation report includes baseline comparison and resource measurements.
- [ ] User guide, troubleshooting guide and release artifacts are complete.

**Implementation discipline:** Build the simplest correct vertical slice; validate with real code and real user workflows; add complexity only after measured evidence justifies it.
