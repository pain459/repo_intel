# Getting Started with repo_intel

This guide walks a new developer through setting up repo_intel from scratch, verifying everything works, connecting OpenCode via MCP, and performing the first productive search.

**Target audience:** You've just cloned the repo and want to see it working.

**Prerequisites:**
- Docker + Docker Compose (v2.20+)
- Git
- OpenCode (for MCP agent integration)
- Access to an Ollama instance with `nomic-embed-text` model (can be local or remote)

---

## Table of Contents

1. [Clone and Setup](#1-clone-and-setup)
2. [Configure Environment](#2-configure-environment)
3. [Start the Stack](#3-start-the-stack)
4. [Verify Everything Works](#4-verify-everything-works)
5. [Register and Index a Repository](#5-register-and-index-a-repository)
6. [Search](#6-search)
7. [Connect OpenCode via MCP](#7-connect-opencode-via-mcp)
8. [Using MCP Tools in OpenCode](#8-using-mcp-tools-in-opencode)
9. [Agent Workflows](#9-agent-workflows)
10. [Monitoring with Prometheus and Grafana](#10-monitoring-with-prometheus-and-grafana)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Clone and Setup

```bash
git clone https://github.com/pain459/repo_intel.git
cd repo_intel
```

The repository contains:
- `compose.yaml` — Docker services (api, worker, postgres, prometheus, grafana)
- `Dockerfile` — Python 3.12 environment
- `src/repo_intel/` — Application code
- `tests/` — Test suite (154 tests)
- `docs/` — Documentation
- `monitoring/` — Prometheus + Grafana configuration

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:
```
DATABASE_URL=postgresql+psycopg://repo_intel:your-secure-password@postgres:5432/repo_intel
OLLAMA_BASE_URL=http://192.168.68.62:11434      # your Ollama address
```

**Key settings:**

| Variable | What it controls |
|----------|-----------------|
| `DATABASE_URL` | PostgreSQL connection string (set a real password) |
| `OLLAMA_BASE_URL` | Where your Ollama server runs |
| `EMBEDDING_MODEL` | Embedding model (default: `nomic-embed-text`) |
| `HOST_REPO_ROOT` | (compose only) Path mounted as `/workspace` |

**Profiles:**
- `local` — Ollama runs on `localhost:11434`
- `remote-ollama` — Ollama runs on a separate machine (default)

---

## 3. Start the Stack

```bash
docker compose up -d --build
```

This starts five services:

| Service | URL | What it does |
|---------|-----|-------------|
| **api** | `http://127.0.0.1:8765` | FastAPI server (REST + MCP + health + metrics) |
| **worker** | — | Background indexing job processor |
| **postgres** | — | PostgreSQL 16 + pgvector extension |
| **prometheus** | `http://127.0.0.1:9090` | Metrics scraper (scrapes `/metrics` every 15s) |
| **grafana** | `http://127.0.0.1:3000` | Dashboards (default login: `admin`/`admin`) |

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

---

## 7. Connect OpenCode via MCP

repo_intel exposes an MCP (Model Context Protocol) server at `/mcp/`. OpenCode connects to it and makes all 17 tools available as `tools.repo_intel.*` in Code Mode.

### Option A: `opencode.jsonc` (Recommended)

Create or copy the OpenCode config file:

```bash
cp opencode.jsonc.example opencode.jsonc
```

This writes:

```jsonc
// opencode.jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "repo_intel": {
        "type": "remote",
        "url": "http://localhost:8765/mcp/",
        "oauth": false
      }
    }
  }
}
```

OpenCode reads `opencode.jsonc` on startup, connects to the MCP server at `http://localhost:8765/mcp/`, and automatically discovers all available tools.

**How it works:**
- OpenCode sends an MCP `initialize` request to the server
- The server responds with the list of tools it provides
- OpenCode registers each tool under the namespace `tools.repo_intel.<tool_name>`
- In Code Mode, you call tools like `tools.repo_intel.repo_search(...)`

### Option B: CLI Configurator

If you prefer the MCP config to be written to `~/.config/opencode/mcp.json` instead of a project-local `opencode.jsonc`, use the CLI:

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

This:
1. Reads the server host/port from settings (default `127.0.0.1:8765`)
2. Builds a config JSON with the MCP endpoint URL
3. Writes it to `~/.config/opencode/mcp.json`

Both options achieve the same result — OpenCode connects to the repo_intel MCP server. Use whichever config location you prefer.

### Verify the Connection

1. Make sure the stack is running: `docker compose ps`
2. Start OpenCode in your project directory (where `opencode.jsonc` exists)
3. Enter Code Mode and run:

```python
tools.repo_intel.repo_list()
```

If you see your registered repositories, the MCP connection is working.

If tools don't appear, see [Troubleshooting: MCP Issues](#mcp-tools-not-discovered).

---

## 8. Using MCP Tools in OpenCode

Once connected, the following tools are available in Code Mode under `tools.repo_intel.*`:

### Repository Tools

| Tool | Description |
|------|-------------|
| `tools.repo_intel.repo_list()` | List all registered repos with file/chunk counts |
| `tools.repo_intel.repo_search(query, repository_id?, limit?)` | Hybrid search (exact + FTS + vector + symbol) |
| `tools.repo_intel.repo_symbol(symbol_name, repository_id?)` | Find class/function definitions by name |
| `tools.repo_intel.repo_context(task_description, repository_id?, token_budget?)` | Build a curated evidence pack up to a token budget |
| `tools.repo_intel.index_status(repository_id)` | Get detailed index status for a repo |
| `tools.repo_intel.repo_dependencies(symbol_name, direction, depth)` | Traverse the symbol dependency graph |

### Memory Tools

| Tool | Description |
|------|-------------|
| `tools.repo_intel.memory_write(kind, statement, ...)` | Record a preference, observation, or instruction |
| `tools.repo_intel.memory_search(query?, kind?, repository_id?, limit?)` | Query stored memories |
| `tools.repo_intel.memory_record(...)` | Legacy alias for `memory_write` |

### Session & Checkpoint Tools

| Tool | Description |
|------|-------------|
| `tools.repo_intel.checkpoint_save(objective, session_id, ...)` | Save task progress |
| `tools.repo_intel.checkpoint_get(session_id?)` | Retrieve latest checkpoint |
| `tools.repo_intel.task_resume(...)` | Legacy alias for `checkpoint_get` |
| `tools.repo_intel.compaction_checkpoint_save(...)` | Checkpoint optimized for compaction recovery |
| `tools.repo_intel.session_bootstrap(session_id?)` | Restore session state after compaction |

See [Usage Guide](USAGE.md) for detailed parameter reference and examples for every tool.

---

## 9. Agent Workflows

### Code Investigation

```python
# 1. List repos
tools.repo_intel.repo_list()

# 2. Search for relevant code
tools.repo_intel.repo_search(query="authentication middleware", limit=5)

# 3. Look up a specific symbol
tools.repo_intel.repo_symbol(symbol_name="AuthMiddleware")

# 4. Build a complete context pack
tools.repo_intel.repo_context(
    task_description="Explain the auth flow",
    token_budget=8000
)

# 5. Explore what the symbol depends on
tools.repo_intel.repo_dependencies(
    symbol_name="AuthMiddleware",
    direction="outgoing",
    depth=2
)
```

### Long-Session Workflow with Checkpoints

```python
# Start of session: save checkpoint
tools.repo_intel.checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    pending_steps=["Profile search", "Optimize vector index", "Add tests"]
)

# After some work: update checkpoint
tools.repo_intel.checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    current_state="Vector index optimized, 20% faster",
    changed_files=["src/retrieval/search.py"],
    pending_steps=["Add tests", "Write docs"]
)

# Before context compaction: save a compaction-optimized checkpoint
tools.repo_intel.compaction_checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    changed_files=["src/retrieval/search.py", "tests/test_retrieval.py"]
)

# After compaction: restore everything
state = tools.repo_intel.session_bootstrap(session_id="search-refactor")
```

### Remember What You Learn

```python
# Save a discovery
tools.repo_intel.memory_write(
    kind="observation",
    statement="The agent-memory repo uses TypeScript for its proxy layer",
    repository_id="4f69d864-aea3-443f-95f9-5376c7cddb9c"
)

# Later: query and verify
tools.repo_intel.memory_search(query="proxy layer", kind="observation")
```

---

## 10. Monitoring with Prometheus and Grafana

The Docker Compose stack includes Prometheus and Grafana pre-configured for repo_intel.

### Access the Dashboards

| Service | URL | Credentials |
|---------|-----|-------------|
| **Prometheus** | http://127.0.0.1:9090 | — |
| **Grafana** | http://127.0.0.1:3000 | `admin` / `admin` |

### Grafana Dashboard

The "repo_intel Dashboard" loads automatically when Grafana starts. It includes panels for:

- **Service Health** — uptime, open file descriptors, resident memory, CPU usage
- **Search Performance** — request rate, p50/p90/p95/p99 latency, latency distribution over time
- **Indexing** — chunks indexed per minute, cumulative total
- **Python / GC** — garbage collection rate and objects collected by generation

Prometheus scrapes the API's `/metrics` endpoint every 15 seconds and retains data for 7 days.

### Custom Metrics

The API exposes these repo_intel-specific metrics in Prometheus format:

| Metric | Type | Description |
|--------|------|-------------|
| `repo_intel_search_requests_total` | Counter | Total searches by method (exact, fts, vector, symbol) |
| `repo_intel_search_latency_seconds` | Histogram | Search latency buckets |
| `repo_intel_index_chunks_total` | Counter | Total chunks indexed by type |

You can also fetch raw metrics directly:

```bash
curl http://127.0.0.1:8765/metrics
```

See [Operations Guide](OPERATIONS.md) for production monitoring tips.

---

## 11. Troubleshooting

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

### MCP Tools Not Discovered

1. Check `opencode.jsonc` exists and points to the correct URL:
   ```jsonc
   { "mcp": { "servers": { "repo_intel": { "type": "remote", "url": "http://localhost:8765/mcp/" } } } }
   ```
2. Verify the API is healthy:
   ```bash
   curl -sf http://localhost:8765/health/live
   ```
3. Verify the MCP endpoint responds:
   ```bash
   curl -s http://localhost:8765/api/mcp/tools | python3 -m json.tool
   ```
   Should list 17 tools.
4. Restart OpenCode after making config changes.

### Worker not processing jobs

```bash
docker compose logs worker --tail=20
docker compose restart worker
```

### Prometheus isn't scraping metrics

Check inside the Prometheus container:

```bash
docker compose exec prometheus wget -q -O - http://localhost:9090/api/v1/targets
```

Look for the `repo_intel` target with `"health":"UP"`.

### Performance Issues

```bash
# Memory/CPU per container
docker compose stats

# Slow DB queries
docker compose exec postgres psql -U repo_intel repo_intel -c \
  "SELECT query, calls, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 5;"
```

For detailed troubleshooting, see [Troubleshooting Guide](TROUBLESHOOTING.md).

---

## Next Steps

- Read the [Usage Guide](USAGE.md) for detailed MCP tool reference
- Read the [Architecture Guide](ARCHITECTURE.md) for system design details
- Read the [Evaluation Guide](evaluation.md) for quality benchmarks
- Read the [Operations Guide](OPERATIONS.md) for production deployment
