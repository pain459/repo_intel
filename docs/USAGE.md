# Usage Guide

How to use repo_intel as a coding agent operator.

## Connecting OpenCode to repo_intel

### Quick Setup

```bash
cp opencode.jsonc.example opencode.jsonc
```

OpenCode will auto-connect to the MCP server on startup and discover all 14 tools.

### Alternative: CLI Configurator

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

### Verify Connection

In OpenCode, the MCP tools appear under `tools.repo_intel.*`. Test:

```python
tools.repo_intel.repo_list()
```

---

## MCP Tools Reference (14)

All tools are available through MCP at `http://localhost:8765/mcp/`.

### Repository Tools

#### 1. `repo_list` — List Registered Repositories

```python
tools.repo_intel.repo_list()
```

Returns repository names, file counts, chunk counts, and indexing status.

#### 2. `repo_search` — Hybrid Search

Combines exact match, full-text search, semantic vector retrieval, and symbol expansion with RRF fusion (K=60).

```python
tools.repo_intel.repo_search(
    query="how does the indexer discover files",
    repository_id="uuid",  # optional
    limit=5
)
```

#### 3. `repo_symbol` — Symbol Lookup

Find class, function, or variable definitions by name.

```python
tools.repo_intel.repo_symbol(symbol_name="IndexGeneration")
```

#### 4. `repo_context` — Build Evidence Packs

Search indexed repos and return relevant code chunks up to a token budget.

```python
tools.repo_intel.repo_context(
    task_description="How does the hybrid search pipeline work?",
    token_budget=12000
)
```

#### 5. `index_status` — Index Health Check

Get detailed status for a specific repository.

```python
tools.repo_intel.index_status(repository_id="uuid")
```

#### 6. `repo_dependencies` — Dependency Graph Traversal

Traverse the symbol dependency graph (BFS, bounded depth).

```python
tools.repo_intel.repo_dependencies(
    symbol_name="UserModel",
    direction="outgoing",  # or "incoming"
    depth=2
)
```

Returns up to 50 edges with evidence locations and confidence scores.

---

### Memory Tools

#### 7. `memory_write` — Record Agent Memory

Write a preference, observation, instruction, or pattern.

```python
tools.repo_intel.memory_write(
    kind="preference",
    statement="Use ruff for linting",
    evidence={"source": "pyproject.toml"}
)
```

**Kinds:** `preference` | `observation` | `instruction` | `pattern`

#### 8. `memory_read` — Query Memories

```python
tools.repo_intel.memory_read(
    query="linting",
    kind="preference",
    limit=20
)
```

#### 9. `memory_record` — Write Memory (Legacy Alias)

Alias for `memory_write`.

---

### Checkpoint Tools

#### 10. `checkpoint_save` — Save Task Progress

```python
tools.repo_intel.checkpoint_save(
    objective="Implement feature X",
    session_id="my-session",
    current_state="Tests passing",
    changed_files=["src/model.py"],
    pending_steps=["Write docs"]
)
```

#### 11. `checkpoint_get` — Retrieve Checkpoint

```python
tools.repo_intel.checkpoint_get(session_id="my-session")
```

#### 12. `task_resume` — Resume Session (Alias)

Alias for `checkpoint_get`.

---

### Compaction Continuity Tools

#### 13. `compaction_checkpoint_save` — Save Before Compaction

Explicit checkpoint optimized for compaction recovery. Tags with compaction marker.

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

Returns the most recent checkpoint and verified memories for quick context reconstruction.

```python
tools.repo_intel.session_bootstrap(
    session_id="my-session"
)
```

Returns:
- Latest checkpoint (objective, state, files, pending steps)
- Up to 20 verified memories
- Scoped to session/repository

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

# Before compaction
tools.repo_intel.compaction_checkpoint_save(
    objective="Refactor the search pipeline",
    session_id="search-refactor",
    changed_files=["src/retrieval/search.py", "tests/test_retrieval.py"]
)

# After compaction: restore state
state = tools.repo_intel.session_bootstrap(session_id="search-refactor")
print(state["checkpoint"]["objective"])   # "Refactor the search pipeline"
print(state["verified_memories"])         # Recent verified memories
```

### Remember What You Learn

```python
# Save a discovery
tools.repo_intel.memory_write(
    kind="observation",
    statement="The agent-memory repo uses TypeScript for its proxy layer",
    repository_id="4f69d864-aea3-443f-95f9-5376c7cddb9c"
)

# Later: verify and reuse
tools.repo_intel.memory_read(query="proxy layer", kind="observation")
```

---

## REST API (Alternative Access)

All functionality available via REST:

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

# Tool list
curl http://localhost:8765/api/mcp/tools

# Metrics
curl http://localhost:8765/metrics
```

See [README.md](../README.md) for the complete endpoint reference.

---

## Security Notes

- Indexed content is redacted before storage (API keys, passwords, tokens)
- Secret files (`.env`, SSH keys, etc.) are excluded from indexing
- Queries pass through a prompt-injection guard
- Logs use structured JSON format with credential filtering
