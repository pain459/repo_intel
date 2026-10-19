# OpenCode Setup Guide

How to connect OpenCode to repo_intel so the agent can use all 17 MCP tools in Code Mode.

---

## Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Your Machine                         │
│                                                          │
│  OpenCode ──MCP──▶  repo_intel API (localhost:8765)     │
│  (opencode.jsonc)          │                             │
│                            │ Docker                      │
│                     ┌──────▼──────┐                      │
│                     │  Containers │                      │
│                     │  api +      │                      │
│                     │  worker +   │                      │
│                     │  postgres   │                      │
│                     └─────────────┘                      │
└─────────────────────────────────────────────────────────┘
```

OpenCode reads an MCP server configuration from `opencode.jsonc`. When repo_intel's MCP server is configured, every tool becomes available as `tools.repo_intel.<tool_name>` inside Code Mode `execute` blocks.

---

## Prerequisites

- repo_intel is running (`docker compose up -d --build`)
- Health checks pass: `curl http://localhost:8765/health/ready` returns `{"status":"ok","database":"ok","ollama":"ok"}`
- At least one repository is registered and indexed

If repo_intel isn't running yet, follow [QUICKSTART.md](QUICKSTART.md) first.

---

## 1. Configure OpenCode

OpenCode expects an `opencode.jsonc` file with MCP server definitions. There are two ways to set this up.

### Option A — Use the Example Config (Quick)

```bash
cp opencode.jsonc.example ~/.config/opencode/opencode.jsonc
```

This writes:

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

### Option B — Generate via CLI

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

This prompts you to confirm and writes the config to `~/.config/opencode/mcp.json`. The CLI reads the host/port from your `.env` so it stays in sync.

### What the Config Does

| Field | Value | Purpose |
|-------|-------|---------|
| `type` | `"remote"` | Tells OpenCode to connect over HTTP instead of stdio |
| `url` | `http://localhost:8765/mcp/` | The MCP endpoint on the repo_intel API container |
| `oauth` | `false` | No authentication needed (localhost, behind Docker) |

> **Note:** If you bind repo_intel to `0.0.0.0` (remote deployment), update the URL to the actual hostname or IP.

---

## 2. Verify the Connection

### Check MCP Server Responds

```bash
curl -X POST http://localhost:8765/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1}'
```

You should see a JSON-RPC response with server capabilities and the list of tools.

### Check Inside OpenCode

Open a Code Mode session in OpenCode and try:

```
tools.repo_intel["repo_list"]()
```

If it returns a list of repositories (even if empty), the connection is working. If you get `tool not found` or `MCP server could not be mounted`, rebuild:

```bash
docker compose up -d --build
```

And restart OpenCode.

---

## 3. Available MCP Tools

Once connected, 17 tools are available. All are prefixed `tools.repo_intel.` in Code Mode.

### Search & Retrieval

| Tool | Signature | What it does |
|------|-----------|-------------|
| `repo_search` | `(query, repository_id?, limit=10)` | 4-way hybrid search (exact + FTS + semantic + symbol) |
| `repo_symbol` | `(symbol_name, repository_id?)` | Find function/class/variable definitions |
| `repo_context` | `(task_description, repository_id?, token_budget=12000)` | Build a curated evidence pack for a task |
| `repo_dependencies` | `(symbol_name, repository_id?, direction, depth=2)` | Traverse the dependency graph |

### Repository Management

| Tool | Signature | What it does |
|------|-----------|-------------|
| `repo_list` | `()` | List all registered repos with status |
| `index_status` | `(repository_id)` | Detailed indexing state for one repo |

### Agent Memory

| Tool | Signature | What it does |
|------|-----------|-------------|
| `memory_write` | `(kind, statement, ...)` | Save a decision, preference, or observation |
| `memory_record` | *(alias for memory_write)* | Same as above |
| `memory_search` | `(query?, repository_id?, kind?, limit=20)` | Search saved memories |

### Session & Checkpoints

| Tool | Signature | What it does |
|------|-----------|-------------|
| `checkpoint_save` | `(objective, session_id?, ...)` | Save progress for later resumption |
| `checkpoint_get` | `(session_id?, repository_id?)` | Retrieve latest checkpoint |
| `task_resume` | *(alias for checkpoint_get)* | Same as above |
| `session_bootstrap` | `(session_id?, repository_id?)` | Full session restore after compaction |
| `compaction_checkpoint_save` | *(same params as checkpoint_save)* | Checkpoint optimized for compaction recovery |

---

## 4. Model Configuration

repo_intel itself does **not** run an LLM. It uses Ollama for embeddings only. The LLM that powers your OpenCode agent is separate.

### Embedding Model (repo_intel side)

Controlled by `.env`:

```
EMBEDDING_MODEL=nomic-embed-text
OLLAMA_BASE_URL=http://192.168.x.x:11434
```

The `nomic-embed-text` model must be pulled on your Ollama instance:

```bash
# Run on the machine hosting Ollama
curl http://192.168.x.x:11434/api/pull -d '{"name":"nomic-embed-text"}'
```

### Chat/Reasoning Model (OpenCode side)

This is configured in OpenCode's own settings, **not** in repo_intel. Whichever model OpenCode uses for reasoning is the one that calls the MCP tools. Common choices:

| Model | Provider | Notes |
|-------|----------|-------|
| `qwen3.6-resilient` | Ollama | Good for code tasks, runs locally |
| `llama3.3` | Ollama | Strong general-purpose |
| `mistral-large` | Any | Strong reasoning |

OpenCode sends the model's reasoning output to the MCP server, which executes the tool and returns results. The model then incorporates those results into its next response.

### Ensuring the Model Can Use MCP Tools

Some models handle tool calling better than others. If the agent ignores MCP tools:

1. **Check the model supports function calling** — most modern models do
2. **Make the task concrete** — instead of "search the codebase", say "use `tools.repo_intel['repo_search']` to find how authentication works"
3. **Verify MCP tools are registered** — call `tools.repo_intel["repo_list"]()` directly to confirm connectivity

---

## 5. Typical Workflows

### Search + Context Pack

```python
# Find relevant code
results = tools.repo_intel["repo_search"](
    query="database connection pooling configuration",
    limit=10
)

# Build a full context pack for a task
context = tools.repo_intel["repo_context"](
    task_description="Add retry logic to database connections",
    token_budget=12000
)
```

### Symbol Lookup + Dependencies

```python
# Find where a function is defined
sym = tools.repo_intel["repo_symbol"](symbol_name="connect_db")

# See what it depends on
deps = tools.repo_intel["repo_dependencies"](
    symbol_name="connect_db",
    direction="outgoing",
    depth=2
)
```

### Memory Across Sessions

```python
# Save an observation
tools.repo_intel["memory_write"](
    kind="observation",
    statement="The auth module uses JWT with 24h expiry",
    repository_id="<uuid>"
)

# Later, restore context
bootstrap = tools.repo_intel["session_bootstrap"](
    session_id="my-session-id"
)
```

---

## 6. Troubleshooting MCP Connection

| Symptom | Fix |
|---------|-----|
| `MCP server could not be mounted` | Rebuild containers: `docker compose up -d --build` |
| Tools return empty lists | Check repos are indexed: `docker compose exec api repo-intel status` |
| Connection timeout | Verify `http://localhost:8765/mcp/` responds to curl |
| Tools not found in OpenCode | Restart OpenCode after modifying `opencode.jsonc` |
| `ollama` health check fails | Check `OLLAMA_BASE_URL` in `.env`, verify Ollama is running |

---

## Related

- [QUICKSTART.md](QUICKSTART.md) — Get repo_intel running
- [DEVELOPMENT.md](DEVELOPMENT.md) — Architecture and tech stack
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Debugging and crash recovery
