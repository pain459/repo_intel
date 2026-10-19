# repo_intel

> Persistent, searchable knowledge of Git repositories for coding agents.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-latest-009688)](https://fastapi.tiangolo.com/)
[![PostgreSQL+pgvector](https://img.shields.io/badge/postgres-pgvector-green)](https://github.com/pgvector/pgvector)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-orange)](https://modelcontextprotocol.io/)

---

## What it does

- **Indexes** local Git repositories → searchable chunks in PostgreSQL + pgvector
- **Hybrid search**: exact match + full-text + semantic vector + symbol lookup (4-way RRF fusion)
- **MCP tools**: 14 tools exposed to coding agents (OpenCode) for on-demand retrieval
- **Agent memory**: evidence-backed decisions, preferences, and observations with lifecycle management
- **Session checkpoints**: persist and restore work-in-progress across agent sessions
- **Compaction continuity**: survive context compaction with auto-checkpointing and session bootstrap
- **Dependency graph**: heuristic symbol edge detection + BFS traversal tool
- **Prometheus metrics**: `/metrics` endpoint for monitoring search, indexing, and system health

## Quick start (5 minutes)

A new developer can be up and running in five minutes:

```bash
# 1. Clone
git clone https://github.com/pain459/repo_intel.git
cd repo_intel

# 2. Prepare environment
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD and OLLAMA_BASE_URL

# 3. Build and start
docker compose up -d --build

# 4. Verify
docker compose exec api repo-intel doctor
# Expect: all checks PASS

# 5. Register a repository
docker compose exec api repo-intel repo add /workspace

# 6. Trigger indexing
docker compose exec api repo-intel index

# 7. Search
docker compose exec api repo-intel search "how does indexing work"
```

### Or use the installer

```bash
bash scripts/install.sh
bash scripts/verify.sh
```

See [Getting Started Guide](docs/GETTING_STARTED.md) for a complete walkthrough.

## Architecture at a glance

```
┌───────────────────────────────────────────────────────────────────┐
│                         Your Machine                              │
│                                                                   │
│  OpenCode ──MCP──▶  repo_intel-api (FastAPI) :8765               │
│                        ├── /health/*  (liveness/readiness)         │
│                        ├── /api/*     (REST)                       │
│                        ├── /mcp/      (MCP Streamable HTTP)       │
│                        └── /metrics   (Prometheus)                │
│                                                                   │
│  repo_intel-worker (background indexing jobs)                     │
│                                                                   │
│  PostgreSQL + pgvector (named volume, persists across restarts)   │
└────────────────────┬──────────────────────────────────────────────┘
                     │ HTTP (embedding requests)
                     ▼
┌───────────────────────────────────────────────────────────────────┐
│  Remote Ollama (e.g. 192.168.68.62:11434)                        │
│  └── nomic-embed-text → 768-dim vectors                           │
└───────────────────────────────────────────────────────────────────┘
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `repo-intel serve` | Start the FastAPI server |
| `repo-intel worker` | Start the background indexing worker |
| `repo-intel repo add /path` | Register a repository for indexing |
| `repo-intel repo list` | List registered repos |
| `repo-intel repo remove <uuid>` | Remove a repo |
| `repo-intel index` | Trigger an immediate index scan |
| `repo-intel status` | Show repository index status |
| `repo-intel doctor` | Run preflight diagnostics |
| `repo-intel search "query"` | Search indexed repositories |
| `repo-intel benchmark` | Run the retrieval quality benchmark |
| `repo-intel backup` | Dump the database to a compressed SQL file |
| `repo-intel restore <file>` | Restore from backup |
| `repo-intel mcp configure` | Generate MCP client configuration |

## MCP Tools (14)

| # | Tool | Description |
|---|------|-------------|
| 1 | `repo_list` | List registered repositories and index status |
| 2 | `repo_search` | Hybrid search (exact + FTS + vector + symbol) |
| 3 | `repo_symbol` | Find symbol definitions by name |
| 4 | `repo_context` | Build a curated evidence pack |
| 5 | `index_status` | Get detailed index status |
| 6 | `memory_write` | Write agent memory |
| 7 | `memory_read` | Query agent memories |
| 8 | `memory_record` | Alias for memory_write (legacy naming) |
| 9 | `checkpoint_save` | Save a task progress snapshot |
| 10 | `checkpoint_get` | Retrieve latest checkpoint |
| 11 | `task_resume` | Alias for checkpoint_get |
| 12 | `compaction_checkpoint_save` | Save checkpoint for compaction recovery |
| 13 | `session_bootstrap` | Restore session state after compaction |
| 14 | `repo_dependencies` | Traverse symbol dependency graph |

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness (DB + Ollama) |
| `/api/repositories/` | GET/POST | List/register repositories |
| `/api/repositories/{id}/index` | POST | Trigger re-index |
| `/api/search/` | POST | Hybrid search |
| `/api/memory/` | GET/POST | Agent memories CRUD |
| `/api/memory/{id}` | PATCH/DELETE | Update/delete memory |
| `/api/checkpoints/` | GET/POST | Checkpoints CRUD |
| `/api/checkpoints/{id}` | GET/DELETE | Get/delete checkpoint |
| `/api/mcp/tools` | GET | List MCP tools |
| `/api/mcp/call` | POST | Dispatch MCP tool call |
| `/metrics` | GET | Prometheus metrics |

## Configuration

All settings via `.env` (or environment variables). See [.env.example](.env.example).

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_INTEL_PROFILE` | `remote-ollama` | `local` or `remote-ollama` |
| `OLLAMA_BASE_URL` | `http://192.168.68.62:11434` | Ollama endpoint |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `DATABASE_URL` | *(see .env.example)* | PostgreSQL connection string |
| `INDEX_POLL_SECONDS` | `10` | Worker polling interval |
| `MAX_FILE_BYTES` | `1048576` | Max file size (1 MB) |

## Development

```bash
docker compose up -d --build
docker compose exec api pytest tests/ -v     # 154 tests
docker compose exec api ruff check src/ tests/
docker compose exec api bash                 # shell into container
```

## Documentation

| Document | What it covers |
|----------|---------------|
| [Getting Started](docs/GETTING_STARTED.md) | Complete setup walkthrough for a new developer |
| [Usage Guide](docs/USAGE.md) | How to use MCP tools and workflows |
| [Operations](docs/OPERATIONS.md) | Day-to-day operations, monitoring, backups |
| [Architecture](docs/ARCHITECTURE.md) | System design, data models, pipelines |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and fixes |
| [Evaluation](docs/evaluation.md) | Quality benchmarks and metrics |

## Current status

### Phase 1-4: Foundation, Indexing, Retrieval, Memory ✅
### Phase 5: Compaction Continuity ✅
### Phase 6-10: Security, Hardening, Observability, Benchmarks ✅

All v1.0 Definition-of-Done items closed. **154 tests passing**, lint clean.

See [REMAINING_WORK.md](docs/REMAINING_WORK.md) for the full audit.

## License

[To be determined]
