# Development Guide

Architecture overview, technology stack, and development workflow for repo_intel.

---

## Architecture

```
┌──────────────────────┐       MCP (Streamable HTTP)       ┌────────────────────┐
│    OpenCode Agent    │  ──────────────────────────────▶   │  repo_intel API    │
│  (tools.repo_intel*) │                                    │  FastAPI + MCP     │
└──────────────────────┘         JSON-RPC responses         │  :8765             │
                                                             ├──────────────────┤
                                                             │  worker          │
                                                             │  (background     │
                                                             │   indexing jobs) │
                                                             ├─────────────┬────┤
                                                             │  pgvector   │    │
                                                             │  pg16       │    │
                                                             └─────────────┴────┘
```

### Components

| Component | Technology | Role |
|-----------|-----------|------|
| API | FastAPI + Uvicorn | REST endpoints, MCP server, health checks, Prometheus metrics |
| Worker | Custom async loop | Background repository indexing, stale chunk cleanup, index refresh |
| Database | PostgreSQL 16 + pgvector | Stores chunks, embeddings, symbols, memory, checkpoints, dependencies |
| Embeddings | Ollama (`nomic-embed-text`) | Vector embeddings for semantic search |
| MCP | fastmcp | 17 tools exposed to coding agents via JSON-RPC 2.0 |
| CLI | Typer + Rich | `repo-intel` command for admin operations |
| Metrics | Prometheus client | Counters, histograms, gauges on `/metrics` |
| Monitoring | Grafana + Prometheus | Dashboards at `http://localhost:3000` |

---

## Technology Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| Framework | FastAPI (async), Uvicorn |
| ORM | SQLAlchemy 2.0 (async), Alembic migrations |
| Database | PostgreSQL 16 + pgvector extension |
| Embeddings | Ollama (`nomic-embed-text`) |
| MCP server | fastmcp ≥ 2.3.1 |
| CLI | Typer + Rich |
| Structured logging | structlog |
| Testing | pytest + pytest-asyncio |
| Code quality | ruff |
| Containerization | Docker Compose |
| Monitoring | Prometheus + Grafana |
| Packaging | setuptools, pyproject.toml |

---

## Data Model

Key tables:

| Table | Purpose |
|-------|---------|
| `repositories` | Registered repos, paths, language, status |
| `index_chunks` | Source chunks with embeddings, metadata |
| `index_status` | Per-repo indexing state and progress |
| `symbols` | Detected functions, classes, variables |
| `symbol_edges` | Heuristic dependency graph between symbols |
| `memory_records` | Agent memory: decisions, preferences, observations |
| `session_checkpoints` | Session state for compaction continuity |
| `retrieval_events` | Audit log of search queries and results |

Migrations managed via Alembic. Run `docker compose exec api alembic current` to check applied revisions.

---

## Search Pipeline

repo_intel uses **4-way hybrid retrieval** with Reciprocal Rank Fusion (RRF, k=60):

1. **Exact** — substring match on chunk content
2. **Lexical** — PostgreSQL full-text search
3. **Semantic** — pgvector cosine similarity on embeddings
4. **Symbol** — symbol-name expansion for identifiers

Each sub-search returns scored results. RRF fuses them into a single ranked list. Queries pass through a prompt-injection guard before execution.

---

## MCP Tools (17 total)

| Tool | Purpose |
|------|---------|
| `repo_search` | Hybrid search across indexed repos |
| `repo_symbol` | Find symbol definitions by name |
| `repo_dependencies` | Traverse dependency graph |
| `repo_list` | List registered repositories |
| `repo_status` | Indexing status of repositories |
| `memory_record` / `memory_search` | Agent memory CRUD and search |
| `session_checkpoint` / `session_bootstrap` | Session state persistence |
| `checkpoint_get` | Retrieve latest checkpoint |
| `index_status` | Detailed index state |
| `repo_intel.index_status` | (alias) index status |
| `repo_intel.repo_list` | (alias) list repos |
| `repo_intel.repo_search` | (alias) hybrid search |
| `repo_intel.session_bootstrap` | (alias) session bootstrap |
| `task_resume` | Resume from checkpoint |
| `memory_search` | Semantic search in agent memory |
| `session_move` | Move session to another directory |
| `worktree_create` / `worktree_list` / `worktree_remove` | Git worktree management |

Tools are instrumented with Prometheus counters (success/error) and latency histograms.

---

## Development Workflow

### Run Tests

```bash
docker compose exec api pytest tests/
```

All 154 tests should pass. Lint check:

```bash
docker compose exec api ruff check src/ tests/
```

### Database Migrations

```bash
# Generate a new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply pending migrations
docker compose exec api alembic upgrade head

# Check current state
docker compose exec api alembic current
```

### Add a New MCP Tool

1. Define the function in `src/repo_intel/mcp/fastmcp.py`
2. Decorate with `@_instrument_tool` for metrics
3. Add tests in `tests/`
4. Run `pytest tests/` and `ruff check`

### Monitoring

- **Prometheus**: `http://localhost:9090`
- **Grafana**: `http://localhost:3000` (admin / admin)
- **Metrics endpoint**: `http://localhost:8765/metrics`

The dashboard has 6 sections: overview, search performance, MCP tool calls, database health, worker status, and resource usage.

---

## Docker Volume Cleanup

The PostgreSQL data volume is `repo_intel_pgdata`. To reset:

```bash
docker compose down -v   # ⚠️ destroys all indexed data
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Only do this in development. Always export before destroying volumes in production.

---

## Related

- [QUICKSTART.md](QUICKSTART.md) — Step-by-step setup for new users
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Debugging and crash recovery
