# Getting Started with repo_intel

This guide walks a new developer through setting up repo_intel from scratch, verifying everything works, and performing the first productive search.

**Target audience:** You've just cloned the repo and want to see it working.

**Prerequisites:**
- Docker + Docker Compose (v2.20+)
- Git
- Access to an Ollama instance with `nomic-embed-text` model (can be local or remote)

---

## Table of Contents

1. [Clone and Setup](#1-clone-and-setup)
2. [Configure Environment](#2-configure-environment)
3. [Start the Stack](#3-start-the-stack)
4. [Verify Everything Works](#4-verify-everything-works)
5. [Register and Index a Repository](#5-register-and-index-a-repository)
6. [Search](#6-search)
7. [Connect OpenCode](#7-connect-opencode)
8. [Agent Workflows](#8-agent-workflows)
9. [Monitor and Maintain](#9-monitor-and-maintain)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Clone and Setup

```bash
git clone https://github.com/pain459/repo_intel.git
cd repo_intel
```

The repository contains:
- `compose.yaml` — Docker services (api, worker, postgres)
- `Dockerfile` — Python 3.12 environment
- `src/repo_intel/` — Application code
- `tests/` — Test suite (154 tests)
- `docs/` — Documentation

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:
```
POSTGRES_PASSWORD=your-secure-password
OLLAMA_BASE_URL=http://192.168.68.62:11434      # your Ollama address
```

**Key settings:**

| Variable | What it controls |
|----------|-----------------|
| `POSTGRES_PASSWORD` | Database password (must be set) |
| `OLLAMA_BASE_URL` | Where your Ollama server runs |
| `EMBEDDING_MODEL` | Embedding model (default: `nomic-embed-text`) |
| `DATABASE_URL` | Auto-built from above; don't override unless needed |
| `HOST_REPO_ROOT` | (compose only) Path mounted as `/workspace` |

**Profiles:**
- `local` — Ollama runs on `localhost:11434`
- `remote-ollama` — Ollama runs on a separate machine (default)

---

## 3. Start the Stack

```bash
docker compose up -d --build
```

This starts three services:

| Service | What it does |
|---------|-------------|
| **api** | FastAPI server on `127.0.0.1:8765` (REST + MCP + health + metrics) |
| **worker** | Background indexing job processor |
| **postgres** | PostgreSQL 16 + pgvector extension |

Wait ~15 seconds for all services to become healthy:

```bash
docker compose ps
# Expect: all services "healthy" or "Up"
```

**Your indexed repos are mounted read-only.** By default `/workspace` points to the current directory. To index additional repos, add volume mounts in `compose.yaml`:

```yaml
volumes:
  - /path/on/host/repo:/repos/my-repo:ro
```

---

## 4. Verify Everything Works

### Health Checks

```bash
# Liveness
docker compose exec api curl -sf http://127.0.0.1:8765/health/live
# → {"status":"ok"}

# Readiness (DB + Ollama)
docker compose exec api curl -sf http://127.0.0.1:8765/health/ready
# → {"status":"ok","database":"ok","ollama":"ok"}
```

### Diagnostics

```bash
docker compose exec api repo-intel doctor
```

Expected output:
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Check                       ┃ Status          ┃ Detail         ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ Environment configured      │ PASS            │ profile=...    │
│ PostgreSQL reachable        │ PASS            │ connected      │
│ Ollama reachable            │ PASS            │ ok, models: ...│
│ Embedding model configured  │ PASS            │ model=...      │
│ Network: Ollama DNS         │ PASS            │ resolves       │
└─────────────────────────────┴─────────────────┴────────────────┘

All 5 checks passed.
```

### Prometheus Metrics

```bash
docker compose exec api curl -sf http://127.0.0.1:8765/metrics | head -20
```

Returns Prometheus-format metrics. Key custom metrics:
- `repo_intel_search_requests_total` — counter by search method
- `repo_intel_search_latency_seconds` — histogram
- `repo_intel_index_chunks_total` — counter by chunk type

See [Operations Guide](OPERATIONS.md) for monitoring setup.

### Tests

```bash
docker compose exec api pytest tests/ -v
# → 154 passed
docker compose exec api ruff check src/ tests/
# → All checks passed!
```

---

## 5. Register and Index a Repository

### Register

```bash
# Auto-detect name from directory
docker compose exec api repo-intel repo add /workspace

# Custom name
docker compose exec api repo-intel repo add --name my-app /workspace
```

### Check Status

```bash
docker compose exec api repo-intel status
```

### Index

```bash
docker compose exec api repo-intel index
```

The indexer will:
1. Discover tracked files via `git ls-files`
2. Chunk text into ~200-line windows with 20% overlap
3. Generate embeddings via Ollama's `nomic-embed-text`
4. Store everything in PostgreSQL

This takes 30s-2min depending on repo size. Watch progress:

```bash
docker compose logs -f worker
```

### Verify Index

```bash
docker compose exec api repo-intel status
# Check that chunk_count > 0
```

---

## 6. Search

### CLI

```bash
docker compose exec api repo-intel search "how does indexing work"
```

Returns hybrid results (exact + FTS + vector + symbol) ranked by Reciprocal Rank Fusion.

### REST API

```bash
curl -X POST http://127.0.0.1:8765/api/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "how does indexing work", "limit": 5}'
```

### MCP (via OpenCode)

```python
tools.repo_intel.repo_search(
    query="how does indexing work",
    limit=5
)
```

---

## 7. Connect OpenCode

### Option A: `opencode.jsonc.example`

```bash
cp opencode.jsonc.example opencode.jsonc
```

OpenCode auto-connects on startup and discovers all 14 MCP tools.

### Option B: CLI Configurator

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

This writes `~/.config/opencode/mcp.json` with the server URL.

### Verify

In OpenCode's Code Mode:
```python
tools.repo_intel.repo_list()
```

Should return your registered repositories.

---

## 8. Agent Workflows

### Code Investigation

```python
# Search for relevant code
tools.repo_intel.repo_search(query="authentication flow", limit=5)

# Look up a specific function
tools.repo_intel.repo_symbol(symbol_name="authenticate_user")

# Build a complete context pack
tools.repo_intel.repo_context(
    task_description="Explain the auth middleware chain",
    token_budget=8000
)
```

### Remember Learnings

```python
tools.repo_intel.memory_write(
    kind="observation",
    statement="The API uses JWT tokens validated via middleware",
    repository_id="uuid-of-repo"
)
```

### Track Progress

```python
# Save checkpoint (every 15-20 min or at milestones)
tools.repo_intel.checkpoint_save(
    objective="Implement auth middleware",
    session_id="auth-task",
    current_state="Draft complete",
    changed_files=["src/auth.py"],
    pending_steps=["Add tests", "Write docs"]
)

# Resume later
tools.repo_intel.checkpoint_get(session_id="auth-task")
```

### Compaction Recovery

When context is about to be compacted:
```python
tools.repo_intel.compaction_checkpoint_save(
    objective="My current objective",
    session_id="my-session",
    changed_files=["src/file.py"]
)
```

After compaction:
```python
tools.repo_intel.session_bootstrap(session_id="my-session")
```

### Dependency Exploration

```python
tools.repo_intel.repo_dependencies("UserModel", direction="outgoing", depth=2)
```

---

## 9. Monitor and Maintain

### Daily Operations

```bash
# Check services
docker compose ps

# Check logs
docker compose logs --tail=20 api
docker compose logs --tail=20 worker

# Rebuild after code changes
docker compose up -d --build
```

### Backups

```bash
# Manual
docker compose exec postgres pg_dump -U repo_intel repo_intel > backup.sql

# CLI (compressed)
docker compose exec api repo-intel backup
```

### Common Maintenance

```bash
# Re-index all repos
docker compose exec api repo-intel index

# Apply DB migrations (usually automatic)
docker compose exec api alembic upgrade head

# Full stack reset (⚠️ destroys data)
docker compose down -v  # Only after backup
```

---

## 10. Troubleshooting

### "Ollama not reachable"
```bash
# Verify Ollama is running and accessible
curl $OLLAMA_BASE_URL/api/tags
```

### Search returns few results
```bash
# Check if chunks have embeddings
docker compose exec postgres psql -U repo_intel repo_intel -c \
  "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL;"
# If 0: trigger re-index
```

### Worker not processing jobs
```bash
docker compose logs worker --tail=20
docker compose restart worker
```

### MCP not connecting
See [Troubleshooting Guide](TROUBLESHOOTING.md#mcp-endpoint-issues)

### Performance Issues

For large repos, check monitoring:
```bash
# Memory/CPU
docker compose stats

# Slow queries (inside postgres)
docker compose exec postgres psql -U repo_intel repo_intel -c \
  "SELECT query, calls, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 5;"
```

---

## Next Steps

- Read the [Usage Guide](USAGE.md) for detailed MCP tool reference
- Read the [Architecture Guide](ARCHITECTURE.md) for system design details
- Read the [Evaluation Guide](evaluation.md) for quality benchmarks
- Read the [Operations Guide](OPERATIONS.md) for production deployment
