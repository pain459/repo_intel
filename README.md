# repo_intel

Persistent, searchable knowledge of Git repositories for coding agents.

## What it does

- Index a local Git repository and store searchable embeddings in PostgreSQL + pgvector
- Hybrid search: exact match + full-text + semantic vector retrieval
- Expose MCP tools to OpenCode so agents can retrieve code evidence on demand
- Record evidence-backed decisions and task checkpoints across sessions

## Quick start (Phase 1)

```bash
# 1. Prepare .env (install.sh creates it from .env.example)
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, adjust OLLAMA_BASE_URL, etc.

# 2. Build and start the stack
docker compose up -d --build

# 3. Apply DB migrations
docker compose exec api alembic upgrade head

# 4. Run diagnostics
docker compose exec api repo-intel doctor
```

### Or use the installer

```bash
bash scripts/install.sh
bash scripts/verify.sh
```

## Architecture

- **API** — FastAPI on `127.0.0.1:8765` (health, search, MCP — Phase 3+)
- **Worker** — background indexing jobs (Phase 2+)
- **PostgreSQL** — pgvector extension, namespaced volume, persists across restarts
- **Ollama** — local or remote (e.g. `http://192.168.68.62:11434`)

See the [implementation plan](repo_intel_implementation_plan.md) for full details.

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

## Development

```bash
# Start the stack
make up

# Run tests
make test

# Run linter
make lint
```

## Current status

**Phase 1** — Foundation and deployment complete:
- [x] Project skeleton, Python packaging, typed configuration
- [x] FastAPI app with `/health/live` and `/health/ready`
- [x] Docker + Compose with API, worker, PostgreSQL/pgvector
- [x] Alembic migration baseline
- [x] CLI (`doctor`, `status`, `serve`, `worker`)
- [x] Install and verify scripts
- [x] Unit tests

**Next:** Phase 2 — repository ingestion and indexing.
