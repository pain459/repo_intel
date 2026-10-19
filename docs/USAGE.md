# Usage Guide

How to use repo_intel as a coding agent operator.

## Connecting OpenCode to repo_intel

### Quick Setup

```bash
cp opencode.jsonc.example opencode.jsonc
```

OpenCode will auto-connect to the MCP server on startup and discover all 9 tools.

### Verify Connection

In OpenCode, the MCP tools appear in the Code Mode tool catalog as `tools.repo_intel.*`.
Test it:

```python
# In Code Mode execute block
tools.repo_intel.repo_list()
```

Should return list of registered repositories.

## MCP Tools Reference

All 9 tools are available through the MCP protocol at `http://localhost:8765/mcp/`.

### 1. `repo_list` — List Registered Repositories

```python
tools.repo_intel.repo_list()
```

Returns repository names, file counts, chunk counts, and indexing timestamps.

**Response:**
```json
{
  "repositories": [
    {
      "id": "uuid",
      "name": "agent-memory",
      "path": "/repos/agent-memory",
      "status": "indexed",
      "file_count": 1211,
      "chunk_count": 11119,
      "embedding_model": "nomic-embed-text",
      "indexed_at": "2026-10-19 03:10:22"
    }
  ]
}
```

### 2. `repo_search` — Hybrid Search

Combines exact match, full-text search, and semantic vector retrieval with reciprocal rank fusion (RRF, K=60).

```python
tools.repo_intel.repo_search(
    query="how does the indexer discover files",
    repository_id="4f69d864-aea3-443f-95f9-5376c7cddb9c",  # optional
    limit=5
)
```

**Parameters:**
- `query` (required): Search query string
- `repository_id` (optional): Scope to a specific repo UUID
- `limit` (default 10): Maximum results

**Response:**
```json
{
  "query": "...",
  "num_results": 5,
  "results": [
    {
      "path": "src/indexing/indexer.py",
      "start_line": 45,
      "end_line": 78,
      "text": "...",
      "retrieval_methods": ["lexical", "semantic"],
      "score": 0.0164
    }
  ]
}
```

### 3. `repo_symbol` — Symbol Lookup

Find class, function, or variable definitions by name (partial match supported).

```python
tools.repo_intel.repo_symbol(
    symbol_name="IndexGeneration",
    repository_id="uuid"  # optional
)
```

**Response:**
```json
{
  "symbol": "IndexGeneration",
  "definitions": [
    {
      "name": "IndexGeneration",
      "kind": "class",
      "file": "src/repo_intel/db/models.py",
      "start_line": 72,
      "end_line": 95
    }
  ]
}
```

### 4. `repo_context` — Build Evidence Packs

Search indexed repos and return relevant code chunks up to a token budget.

```python
tools.repo_intel.repo_context(
    task_description="How does the hybrid search pipeline work?",
    repository_id="uuid",  # optional
    token_budget=12000     # default
)
```

**Response:**
```json
{
  "task": "...",
  "num_chunks": 8,
  "estimated_tokens": 9500,
  "chunks": [
    {
      "path": "src/retrieval/search.py",
      "start_line": 1,
      "end_line": 85,
      "text": "...",
      "retrieval_methods": ["semantic"]
    }
  ]
}
```

### 5. `index_status` — Index Health Check

Get detailed status for a specific repository.

```python
tools.repo_intel.index_status(repository_id="uuid")
```

**Response:**
```json
{
  "repository_id": "uuid",
  "name": "agent-memory",
  "status": "indexed",
  "active_generation": {
    "id": "uuid",
    "embedding_model": "nomic-embed-text",
    "chunk_count": 11119,
    "created_at": "2026-10-19 03:10:22"
  },
  "last_job": {
    "id": "uuid",
    "type": "initial_scan",
    "status": "completed"
  }
}
```

### 6. `memory_write` — Record Agent Memory

Write a preference, observation, or instruction. Memories start as `candidate` and can be promoted.

```python
tools.repo_intel.memory_write(
    kind="preference",
    statement="Use ruff for linting, never flake8",
    repository_id="uuid",  # optional — omit for global memory
    evidence={"source": "project-standard", "commit": "6efd96a"},
    source_commit="6efd96a"
)
```

**Memory kinds:**
- `preference` — coding style or tool preferences
- `observation` — facts discovered about a codebase
- `instruction` — directives for future work
- `pattern` — architectural or coding patterns used

**Memory statuses:**
- `candidate` (default) → `verified` | `superseded` | `rejected`

### 7. `memory_read` — Query Memories

```python
tools.repo_intel.memory_read(
    query="ruff",           # text search in statements
    kind="preference",       # filter by kind
    repository_id="uuid",    # filter by repo
    limit=20                 # default
)
```

### 8. `checkpoint_save` — Save Task Progress

Persist the current state of work for later resumption.

```python
tools.repo_intel.checkpoint_save(
    objective="Implement hybrid search",
    session_id="my-session",
    repository_id="uuid",
    current_state="All tests passing",
    changed_files=["src/retrieval/search.py", "tests/test_retrieval.py"],
    pending_steps=["Write docs", "Push to main"],
    evidence={"test_count": 64, "pass_rate": 1.0}
)
```

### 9. `checkpoint_get` — Restore Task State

```python
tools.repo_intel.checkpoint_get(
    session_id="my-session",
    repository_id="uuid"  # optional
)
```

Returns the most recent checkpoint for the session.

## Typical Agent Workflows

### Code Investigation

```python
# 1. Search for relevant code
results = tools.repo_intel.repo_search(
    query="how authentication works",
    limit=5
)

# 2. Look up a specific symbol
symbols = tools.repo_intel.repo_symbol(
    symbol_name="AuthMiddleware"
)

# 3. Build context for a task
context = tools.repo_intel.repo_context(
    task_description="How does the auth middleware validate tokens?",
    token_budget=8000
)
```

### Cross-Repo Research

```python
# Search across all repos (no repository_id)
results = tools.repo_intel.repo_search(
    query="error handling retry pattern",
    limit=10
)
```

### Remember What You Learn

```python
# After discovering a pattern, save it as a memory
tools.repo_intel.memory_write(
    kind="observation",
    statement="The agent-memory repo uses TypeScript for its core memory proxy layer",
    repository_id="4f69d864-aea3-443f-95f9-5376c7cddb9c",
)
```

### Track Progress Across Sessions

```python
# Every 15-20 minutes, save a checkpoint
tools.repo_intel.checkpoint_save(
    objective="Phase 5 implementation",
    session_id="phase-5-work",
    current_state="MCP endpoint working, 64 tests passing",
    changed_files=["src/repo_intel/mcp/fastmcp.py"],
    pending_steps=["Add tests for MCP tools", "Update README"],
)

# When resuming, restore state
checkpoint = tools.repo_intel.checkpoint_get(session_id="phase-5-work")
```

## REST API (Alternative Access)

All MCP tools also available via REST:

```bash
# Search
curl -X POST http://localhost:8765/api/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "error handling", "limit": 5}'

# List memories
curl http://localhost:8765/api/memory/

# Get checkpoint
curl http://localhost:8765/api/checkpoints/?session_id=my-session
```

See README.md for the complete endpoint reference.
