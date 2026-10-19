# repo_intel

Persistent, searchable knowledge of Git repositories for coding agents.

## What it does

- Index local Git repositories and store searchable chunks in PostgreSQL + pgvector
- Hybrid search: exact match + full-text + semantic vector retrieval (Phase 3)
- Expose MCP tools to OpenCode so agents can retrieve code evidence on demand (Phase 3+)
- Record evidence-backed decisions and task checkpoints across sessions (Phase 4)

## Quick start

```bash
# 1. Prepare .env (copy from example)
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, adjust OLLAMA_BASE_URL, etc.

# 2. Build and start the stack
docker compose up -d --build

# 3. Apply DB migrations
docker compose exec api alembic upgrade head

# 4. Run diagnostics
docker compose exec api repo-intel doctor

# 5. Register a repository
docker compose exec api repo-intel repo add /workspace

# 6. Trigger indexing
docker compose exec api repo-intel index

# 7. Check status
docker compose exec api repo-intel status
```

### Or use the installer

```bash
bash scripts/install.sh
bash scripts/verify.sh
```

## Architecture

```
MacBook Pro (localhost)                          Ubuntu 192.168.68.62
├── OpenCode native                            └── Ollama :11434
├── Git repos                                      ├── qwen3.6:27b
├── Docker Compose                                 └── nomic-embed-text
│   ├── repo-intel-api (FastAPI) :8765
│   ├── repo-intel-worker (background jobs)
│   └── pgvector:pg16 (data volume)
│
│   └── HTTP → Ollama (embeddings)
```

- **API** — FastAPI on `127.0.0.1:8765` (health, repositories, search)
- **Worker** — background indexing jobs (polling, file discovery, chunking)
- **PostgreSQL** — pgvector extension, named volume, persists across restarts
- **Ollama** — remote at `192.168.68.62:11434` (embeddings only; OpenCode talks directly for coding)

## CLI Commands

| Command                                 | Description                              |
| --------------------------------------- | ---------------------------------------- |
| `repo-intel serve`                      | Start the FastAPI server                 |
| `repo-intel worker`                     | Start the background indexing worker     |
| `repo-intel repo add /path`             | Register a repository for indexing       |
| `repo-intel repo list`                  | List registered repos and index status   |
| `repo-intel index`                      | Trigger an immediate index scan          |
| `repo-intel status`                     | Show repository index status             |
| `repo-intel doctor`                     | Run preflight diagnostics                |

## REST API

| Endpoint                        | Method | Description                          |
| ------------------------------- | ------ | ------------------------------------ |
| `/health/live`                  | GET    | Liveness probe                       |
| `/health/ready`                 | GET    | Readiness (DB + Ollama checks)       |
| `/api/repositories/`            | GET    | List all registered repositories     |
| `/api/repositories/`            | POST   | Register a new repository            |
| `/api/repositories/{id}`        | GET    | Get repository details               |
| `/api/repositories/{id}/index`  | POST   | Trigger re-index                     |

## Development

```bash
# Start the stack
docker compose up -d --build

# Run tests
docker compose exec api pytest tests/ -v

# Run linter
docker compose exec api ruff check src/ tests/

# Shell into API container
docker compose exec api bash
```

## Makefile targets

| Target         | Description                        |
| -------------- | ---------------------------------- |
| `make up`      | Build and start all services       |
| `make down`    | Stop all services                  |
| `make doctor`  | Run diagnostics in the API container |
| `make test`    | Run pytest inside the container    |
| `make migrate` | Apply Alembic migrations           |
| `make logs`    | Follow container logs              |
| `make shell-api` | Bash shell into the API container |

## Current status

### Phase 1 — Foundation ✅ (commit `89e2765`)

- [x] Project skeleton, Python 3.12 packaging, typed configuration (pydantic-settings)
- [x] FastAPI app with `/health/live` and `/health/ready`
- [x] Docker Compose: API, worker, PostgreSQL/pgvector, named volume
- [x] Alembic migration 001 (baseline schema)
- [x] CLI commands: `doctor`, `status`, `serve`, `worker`
- [x] Install and verify scripts
- [x] 3 unit tests passing
- [x] Remote Ollama profile (`192.168.68.62:11434`) — doctor validates connectivity

### Phase 2 — Repository Ingestion and Indexing ✅ (commit `085d59f`)

- [x] Data models: `Repository`, `IndexGeneration`, `FileRecord`, `Chunk`, `Symbol`, `IndexJob`
- [x] Alembic migration 002 (all 6 tables, pgvector 768-dim for nomic-embed-text)
- [x] Text-based chunker with language-aware boundaries (Python, JS/TS, Rust, Go, Java, docs)
- [x] File discovery with `.gitignore` filtering, binary detection, content hashing
- [x] Ollama embedding adapter (`/api/embed`, batch support)
- [x] Indexer orchestrator: file discovery → chunking → DB upsert → job completion
- [x] CLI: `repo add`, `repo list`, `index`, improved `status`
- [x] REST API: `GET/POST /api/repositories/`, trigger re-index
- [x] Background worker with polling job queue
- [x] 26 tests passing, ruff lint clean

### Phase 3 — Hybrid retrieval and MCP (backlog)

- [ ] Exact / FTS / vector candidate search
- [ ] Reciprocal rank fusion, deduplication, context-pack budgeting
- [ ] REST `/api/search` endpoint
- [ ] MCP server + tools for OpenCode integration
- [ ] OpenCode configuration helper

### Phase 4 — Persistent evidence-backed memory (backlog)

- [ ] Memory schema and lifecycle (candidate → verified → superseded)
- [ ] Task checkpoints, cross-session retrieval
- [ ] Memory MCP tools

### Phase 5 — Context continuity (backlog)

- [ ] Optional OpenCode lifecycle hooks
- [ ] Compaction survival and manual fallback

### Phase 6 — Hardening and release (backlog)

- [ ] Evaluation benchmark, backup/restore, security audit
- [ ] Release packaging, user guide, CI artifacts

See [implementation plan](repo_intel_implementation_plan.md) for the full architecture and phase details.

## Configuration

All settings are controlled via `.env` (or environment variables). See [.env.example](.env.example) for the full list.

Key settings:

| Variable               | Default                        | Description                             |
| ---------------------- | ------------------------------ | --------------------------------------- |
| `REPO_INTEL_PROFILE`   | `remote-ollama`                | `local` or `remote-ollama`              |
| `OLLAMA_BASE_URL`      | `http://192.168.68.62:11434`  | Ollama endpoint for embeddings          |
| `EMBEDDING_MODEL`      | `nomic-embed-text`             | Model used for chunk embeddings         |
| `EMBEDDING_BATCH_SIZE` | `16`                           | Embedding requests per batch            |
| `INDEX_POLL_SECONDS`   | `10`                           | Worker polling interval                 |
| `MAX_FILE_BYTES`       | `1048576`                      | Max file size for indexing (1 MB)       |
| `DATABASE_URL`         | *(see .env.example)*           | PostgreSQL connection string            |

## Deployment

The Ubuntu server (`192.168.68.62`) runs **only** Ollama. All repo_intel services (API, worker, PostgreSQL) run locally on the Mac via Docker Compose. The indexed repositories stay local and are mounted read-only into the containers.

No steps are required on the Ubuntu server beyond keeping Ollama running with the embedding model loaded. Both `nomic-embed-text` and the coding model `qwen3.6:27b` are already present.
