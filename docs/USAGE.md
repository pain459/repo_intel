# Usage Guide

How to use repo_intel as a coding agent operator, with OpenCode and MCP tools.

---

## OpenCode MCP Integration

repo_intel provides 17 tools through the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). OpenCode connects to the MCP server automatically when configured, making every tool available as `tools.repo_intel.<tool_name>` in Code Mode.

### How the Connection Works

```
┌─────────────────────┐         MCP (Streamable HTTP)         ┌──────────────────────┐
│                     │  POST http://localhost:8765/mcp/      │                      │
│  OpenCode (IDE)     │  ──────────────────────────────────▶  │  repo_intel API      │
│                     │  ──────────────────────────────────── │  (FastAPI + MCP)      │
│  tools.repo_intel.* │  ← JSON-RPC responses + tools list    │                      │
│                     │                                       │                      │
└─────────────────────┘                                       └──────────────────────┘
```

1. OpenCode reads MCP server configuration from `opencode.jsonc` (project-local) or `~/.config/opencode/mcp.json` (global)
2. On startup, OpenCode sends an MCP `initialize` request to the server
3. The server responds with a tool list
4. OpenCode registers each tool under `tools.repo_intel.<name>`
5. In Code Mode, you call tools directly: `tools.repo_intel.repo_search(...)`

### Configuration

**Option 1: Project-local `opencode.jsonc` (Recommended)**

```bash
cp opencode.jsonc.example opencode.jsonc
```

Contents:
```jsonc
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

**Option 2: Global config via CLI**

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

This writes to `~/.config/opencode/mcp.json`. Useful when you want all OpenCode sessions to have access.

**Option 3: Manual configuration**

```jsonc
// opencode.jsonc
{
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

### Verifying the Connection

After configuring, start OpenCode and enter Code Mode:

```python
# List repositories — should return your indexed repos
tools.repo_intel.repo_list()

# Test search
tools.repo_intel.repo_search(query="indexing", limit=3)
```

If tools don't appear, check the MCP endpoint manually:

```bash
curl -s http://localhost:8765/api/mcp/tools | python3 -m json.tool
```

You should see 17 tools. If this works but OpenCode doesn't discover them, restart OpenCode.

### Tool Namespace

All tools are namespaced under `tools.repo_intel.*`. The full list:

```
tools.repo_intel.repo_list()
tools.repo_intel.repo_search(query, repository_id?, limit?)
tools.repo_intel.repo_symbol(symbol_name, repository_id?)
tools.repo_intel.repo_context(task_description, repository_id?, token_budget?)
tools.repo_intel.index_status(repository_id)
tools.repo_intel.repo_dependencies(symbol_name, direction, depth)
tools.repo_intel.memory_write(kind, statement, ...)
tools.repo_intel.memory_search(query?, kind?, repository_id?, limit?)
tools.repo_intel.memory_record(...)                 # alias for memory_write
tools.repo_intel.checkpoint_save(objective, session_id, ...)
tools.repo_intel.checkpoint_get(session_id?)
tools.repo_intel.task_resume(...)                   # alias for checkpoint_get
tools.repo_intel.compaction_checkpoint_save(...)
tools.repo_intel.session_bootstrap(session_id?)
```

---

## MCP Tools Reference

### Repository Tools

#### 1. `repo_list` — List Registered Repositories

Returns repository names, file counts, chunk counts, embeddings model, and indexing timestamps.

```python
tools.repo_intel.repo_list()
```

**Returns:**
```json
{
  "repositories": [
    {
      "id": "uuid",
      "name": "my-repo",
      "path": "/workspace",
      "status": "indexed",
      "file_count": 1234,
      "chunk_count": 5678,
      "embedding_model": "nomic-embed-text",
      "indexed_at": "2025-10-19T12:00:00"
    }
  ]
}
```

#### 2. `repo_search` — Hybrid Search

Combines exact match, full-text search, semantic vector retrieval, and symbol expansion with RRF fusion (K=60).

```python
tools.repo_intel.repo_search(
    query="how does the indexer discover files",
    repository_id="uuid",  # optional, restricts search to one repo
    limit=5
)
```

**Returns** code chunks with scores, retrieval methods used, line ranges, and staleness flags.

#### 3. `repo_symbol` — Symbol Lookup

Find class, function, or variable definitions by name (partial match supported).

```python
tools.repo_intel.repo_symbol(symbol_name="IndexGeneration")
```

**Returns** symbol name, kind (class/function/variable), file path, line range.

#### 4. `repo_context` — Build Evidence Packs

Search indexed repos and return relevant code chunks up to a token budget. Ideal for providing context to coding agents.

```python
tools.repo_intel.repo_context(
    task_description="How does the hybrid search pipeline work?",
    token_budget=12000
)
```

**Returns** chunks with full text content, token estimates, and retrieval metadata.

#### 5. `index_status` — Index Health Check

Get detailed status for a specific repository, including active generation info and last job status.

```python
tools.repo_intel.index_status(repository_id="uuid")
```

#### 6. `repo_dependencies` — Dependency Graph Traversal

Traverse the symbol dependency graph using BFS with bounded depth.

```python
tools.repo_intel.repo_dependencies(
    symbol_name="UserModel",
    direction="outgoing",  // or "incoming"
    depth=2
)
```

**Returns** up to 50 edges with symbol names, relation types (imports/calls/references), evidence locations, and confidence scores.

---

### Memory Tools

#### 7. `memory_write` — Record Agent Memory

Write a preference, observation, instruction, or pattern.

```python
tools.repo_intel.memory_write(
    kind="preference",
    statement="Use ruff for linting",
    evidence={"source": "pyproject.toml"},
    repository_id="uuid"  // optional, scopes memory to a repo
)
```

**Kinds:** `preference` | `observation` | `instruction` | `pattern`

Memories start with status `candidate` and can later be promoted to `verified` or marked as `superseded`/`rejected`.

#### 8. `memory_search` — Query Memories

```python
tools.repo_intel.memory_search(
    query="linting",
    kind="preference",
    repository_id="uuid",  // optional
    limit=20
)
```

Searches memory statements by text and filters by kind and repository.

#### 9. `memory_record` — Write Memory (Legacy Alias)

Alias for `memory_write`. Kept for backward compatibility with existing workflows.

---

### Checkpoint Tools

#### 10. `checkpoint_save` — Save Task Progress

```python
tools.repo_intel.checkpoint_save(
    objective="Implement feature X",
    session_id="my-session",
    repository_id="uuid",   // optional
    current_state="Tests passing",
    changed_files=["src/model.py"],
    pending_steps=["Write docs"]
)
```

Checkpoints are timestamped and grouped by `session_id` for reliable restoration.

#### 11. `checkpoint_get` — Retrieve Checkpoint

```python
tools.repo_intel.checkpoint_get(
    session_id="my-session",
    repository_id="uuid"   // optional
)
```

Returns the most recent checkpoint for the session/repository.

#### 12. `task_resume` — Resume Session (Legacy Alias)

Alias for `checkpoint_get`.

---

### Compaction Continuity Tools

#### 13. `compaction_checkpoint_save` — Save Before Compaction

Explicit checkpoint optimized for compaction recovery. Tags with a compaction marker and captures current verified memories.

```python
tools.repo_intel.compaction_checkpoint_save(
    objective="My objective",
    session_id="my-session",
    current_state="In progress",
    changed_files=["src/file.py"],
    pending_steps=["Finish task"]
)
```

#### 14. `session_bootstrap` — Restore After Compaction

Returns the most recent checkpoint and verified memories for quick context reconstruction after compaction or restart.

```python
tools.repo_intel.session_bootstrap(session_id="my-session")
```

**Returns:**
- Latest checkpoint (objective, state, files, pending steps)
- Up to 20 verified memories scoped to the session/repository

---

## Typical Agent Workflows

### Code Investigation

```python
# 1. List repos
repos = tools.repo_intel.repo_list()

# 2. Search for relevant code
results = tools.repo_intel.repo_search(
    query="authentication middleware",
    limit=5
)

# 3. Look up a symbol
symbols = tools.repo_intel.repo_symbol(symbol_name="AuthMiddleware")

# 4. Build complete context
context = tools.repo_intel.repo_context(
    task_description="Explain the auth flow",
    token_budget=8000
)

# 5. Explore dependencies
deps = tools.repo_intel.repo_dependencies(
    symbol_name="AuthMiddleware",
    direction="outgoing",
    depth=2
)
```

### Long-Session Workflow

Useful for sessions that span hours and may undergo context compaction:

```python
# Start of session: checkpoint your objective
tools.repo_intel.checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    pending_steps=["Profile search", "Optimize vector index", "Add tests"]
)

# Every 15-20 minutes: update checkpoint
tools.repo_intel.checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    current_state="Vector index optimized, 20% faster",
    changed_files=["src/retrieval/search.py"],
    pending_steps=["Add tests", "Write docs"]
)

# Before compaction: save optimized checkpoint
tools.repo_intel.compaction_checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    changed_files=["src/retrieval/search.py", "tests/test_retrieval.py"]
)

# --- COMPaction happens here ---

# After compaction: restore state
state = tools.repo_intel.session_bootstrap(session_id="search-refactor")
print(state["checkpoint"]["objective"])   # "Refactor the search pipeline"
print(state["verified_memories"])         # Recent verified memories
```

The AutoCheckpointScheduler runs every 15 minutes in the background, automatically marking old checkpoints as stale to keep the database clean.

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

## REST API (Alternative Access)

All functionality is also available via REST endpoints:

```bash
# Search
curl -X POST http://localhost:8765/api/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "error handling", "limit": 5}'

# Memories
curl http://localhost:8765/api/memory/
curl -X POST http://localhost:8765/api/memory/ \
  -H "Content-Type: application/json" \
  -d '{"kind":"preference","statement":"Use ruff"}'

# Checkpoints
curl -X POST http://localhost:8765/api/checkpoints/ \
  -H "Content-Type: application/json" \
  -d '{"objective":"My task","session_id":"s1"}'
curl "http://localhost:8765/api/checkpoints/?session_id=s1"

# Tool list (MCP-discovered tools)
curl http://localhost:8765/api/mcp/tools

# Metrics (Prometheus format)
curl http://localhost:8765/metrics
```

See [README.md](../README.md) for the complete endpoint reference.

---

## Security Notes

- Indexed content is redacted before storage (API keys, passwords, tokens)
- Secret files (`.env`, SSH keys, etc.) are excluded from indexing
- Queries pass through a prompt-injection guard
- Logs use structured JSON format with credential filtering
