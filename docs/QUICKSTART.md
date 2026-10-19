# Quick Start

Get repo_intel running and indexing your first repository in under 5 minutes.

---

## 1. Clone and Configure

```bash
git clone https://github.com/your-org/repo_intel.git
cd repo_intel
cp .env.example .env
```

Edit `.env` — at minimum, change these values:

| Variable | What to set |
|----------|-------------|
| `POSTGRES_PASSWORD` | Any secure password |
| `DATABASE_URL` | Use the same password: `postgresql+psycopg://repo_intel:<PASSWORD>@postgres:5432/repo_intel` |
| `OLLAMA_BASE_URL` | Your Ollama endpoint (e.g., `http://192.168.x.x:11434`) |

The rest of the defaults work fine.

---

## 2. Start the Stack

```bash
docker compose up -d --build
```

This starts 5 services:

- **postgres** — database with pgvector
- **api** — FastAPI server on port 8765
- **worker** — background indexing jobs
- **prometheus** — metrics collector on port 9090
- **grafana** — dashboards on port 3000 (login: `admin` / `admin`)

Wait ~15 seconds for everything to become healthy:

```bash
docker compose ps
curl http://localhost:8765/health/live   # {"status":"ok"}
curl http://localhost:8765/health/ready  # {"status":"ok","database":"ok","ollama":"ok"}
```

---

## 3. Register a Repository

Every repo you want indexed must be **mounted into the containers** first, then **registered** in the database.

### Step 1 — Mount the repo in Docker

Edit `compose.yaml`. Under the `api` service (and `worker` if you want the worker to see it too), add a volume:

```yaml
# compose.yaml, under services.api.volumes
volumes:
  - /Users/ravik/src_git/FLOW:/repos/FLOW:ro
```

Then restart:

```bash
docker compose up -d
```

Verify the path is visible inside the container:

```bash
docker compose exec api ls /repos/FLOW
```

### Step 2 — Register it

```bash
docker compose exec api repo-intel repo add --name "FLOW" /repos/FLOW
```

`--name` is optional — without it, repo_intel uses the directory basename.

### Step 3 — List registered repos

```bash
docker compose exec api repo-intel repo list
```

This shows name, path, status, chunk count, last job status, and file count for every registered repo.

### Register more repos

Repeat the mount + register steps for each repo. For example, to add a second repo called `rea`:

```yaml
# compose.yaml
- /Users/ravik/src_git/rea:/repos/rea:ro
```

```bash
docker compose exec api repo-intel repo add --name "rea" /repos/rea
```

---

## 4. How Indexing Works

repo_intel has **two indexing modes**: automatic (via the worker) and manual (via CLI).

### Automatic Indexing (default)

The `worker` container polls every 10 seconds (configurable via `INDEX_POLL_SECONDS` in `.env`). Each tick:

1. Picks up pending index jobs from the database
2. Compares file content hashes against what's already indexed
3. If **any file changed, was added, or was deleted**, it queues a full re-index for that repo
4. Runs the scan: discovers files, chunks them, generates embeddings, stores symbols

You don't need to do anything — just register the repo and the worker picks it up.

### Manual Indexing

To trigger an index immediately without waiting for the worker:

```bash
# Index a specific repo
docker compose exec api repo-intel index --repo-path /repos/FLOW

# Index all registered repos
docker compose exec api repo-intel index
```

### What gets indexed

- **Chunks**: source code split into searchable blocks with pgvector embeddings
- **Symbols**: functions, classes, variables detected from source
- **Dependencies**: heuristic edges (imports, calls) between symbols
- **File records**: one row per file with content hash for change detection

---

## 5. Check Index Status

### Overall status (all repos)

```bash
docker compose exec api repo-intel status
```

Shows a table with name, path, status, file count, and chunk count.

### Detailed status for one repo (MCP tool)

```python
tools.repo_intel["index_status"](repository_id="<uuid>")
```

Returns the active generation (chunk count, embedding model, timestamp) and the last job (type, status, any error).

### Check worker activity

```bash
# Is the worker running?
docker compose ps worker

# Watch worker logs
docker compose logs -f worker | tail -50
```

The worker prints tick counts every 10 ticks. If ticks are increasing, it's processing.

### Check indexed symbols

```bash
# Count symbols in the database
docker compose exec api psql -U repo_intel -d repo_intel -c \
  "SELECT count(*) FROM symbols;"

# List symbols for a specific repo
docker compose exec api psql -U repo_intel -d repo_intel -c \
  "SELECT s.name, s.kind, f.relative_path FROM symbols s JOIN file_records f ON s.file_id = f.id WHERE f.repository_id = '<uuid>' LIMIT 20;"
```

---

## 6. Search

The query is a **positional argument**. Use `--repo-path` to scope to a repo.

```bash
# Search all repos
docker compose exec api repo-intel search "authentication"

# Scope to FLOW
docker compose exec api repo-intel search "database connection" --repo-path /repos/FLOW

# Limit results
docker compose exec api repo-intel search "error handling" --limit 5
```

### Via the API

```bash
curl -X POST http://localhost:8765/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how does authentication work", "limit": 10}'
```

---

## 7. What to Do If Indexing Doesn't Work

### Symptom: repo stays `registered`, never `indexed`

```bash
# 1. Is the worker running?
docker compose ps worker

# 2. Are there errors in worker logs?
docker compose logs worker | tail -30

# 3. Is the repo path accessible inside the container?
docker compose exec api ls /repos/FLOW
```

### Symptom: index command finishes but chunk count is 0

```bash
# 1. Check if any jobs are stuck
docker compose exec api psql -U repo_intel -d repo_intel -c \
  "SELECT id, repository_id, status, error_summary FROM index_jobs ORDER BY created_at DESC LIMIT 10;"

# 2. Check Ollama is reachable (needed for embeddings)
curl http://localhost:8765/health/ready

# 3. Re-index manually
docker compose exec api repo-intel index --repo-path /repos/FLOW
```

### Symptom: worker crashed or stuck

```bash
# Rebuild and restart
docker compose up -d --build

# Or force-restart just the worker
docker compose restart worker
```

### Symptom: files changed but index didn't update

The worker detects changes by comparing content hashes. If the file changed on disk but the hash matches (e.g., whitespace-only change saved as identical), it won't re-index. Force it:

```bash
docker compose exec api repo-intel index --repo-path /repos/FLOW
```

### Symptom: search returns zero results

```bash
# 1. Is the repo indexed at all?
docker compose exec api repo-intel status

# 2. Check chunk count in DB
docker compose exec api psql -U repo_intel -d repo_intel -c "SELECT count(*) FROM chunks;"

# 3. Try a very simple query
docker compose exec api repo-intel search "import"

# 4. Check for stale chunks (indexed but source file changed)
docker compose exec api psql -U repo_intel -d repo_intel -c "SELECT count(*), stale FROM chunks GROUP BY stale;"
```

---

## 8. Remove a Repository

```bash
# First, see the UUID
docker compose exec api repo-intel repo list

# Remove it (deletes the repo record, all chunks, symbols, and jobs)
docker compose exec api repo-intel repo remove <uuid> --yes
```

Without `--yes`, it prompts for confirmation. This deletes all indexed data for that repo but leaves the other repos and PostgreSQL intact.

---

## 9. Clean Start (Delete Everything)

If you want to wipe all data and start from scratch:

```bash
# 1. Stop containers
docker compose down

# 2. Remove all volumes (⚠️ destroys all indexed data)
docker volume rm repo_intel_pgdata repo_intel_promdata repo_intel_grafanadata 2>/dev/null || true

# 3. Rebuild fresh
docker compose up -d --build

# 4. Run migrations
docker compose exec api alembic upgrade head

# 5. Verify clean state
docker compose exec api repo-intel repo list  # shows "No repositories registered yet"

# 6. Register repos again
docker compose exec api repo-intel repo add --name "FLOW" /repos/FLOW
```

### Partial reset (keep some data)

Remove just the database volume, keep Prometheus and Grafana:

```bash
docker compose down
docker volume rm repo_intel_pgdata
docker compose up -d
docker compose exec api alembic upgrade head
```

---

## 10. Backup and Restore

```bash
# Create a backup (saved to ./backups/ inside the container)
docker compose exec api repo-intel backup

# Custom output directory
docker compose exec api repo-intel backup --output /tmp/backups

# Restore from a backup file
docker compose exec api repo-intel restore /path/to/repo_intel_db_20260101_120000.sql.gz --yes
```

Backup before any destructive operation (volume removal, migration rollback, etc.).

---

## 11. Run Diagnostics

```bash
docker compose exec api repo-intel doctor
```

Checks: environment config, PostgreSQL connectivity, Ollama reachability, embedding model availability, DNS resolution.

---

## 12. Run the Benchmark

```bash
# All repos
docker compose exec api repo-intel benchmark

# Specific repo
docker compose exec api repo-intel benchmark --repository-id <uuid>
```

Runs 10 predefined queries, reports recall, latency, and coverage.

---

## 13. Configure OpenCode MCP

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

Prompts you to confirm, then writes to `~/.config/opencode/mcp.json`.

See [OPENCODE_SETUP.md](OPENCODE_SETUP.md) for model configuration and all MCP tool examples.

---

## 14. Quick MCP Verification

Once OpenCode is configured, test in Code Mode:

```python
# List repos
tools.repo_intel["repo_list"]()

# Search
tools.repo_intel["repo_search"](query="authentication", limit=5)

# Find a symbol
tools.repo_intel["repo_symbol"](symbol_name="authenticate_user")

# Check index status
tools.repo_intel["index_status"](repository_id="<uuid>")

# Build a context pack
tools.repo_intel["repo_context"](task_description="Add login retry logic", token_budget=12000)
```

---

## What's next?

- **[OPENCODE_SETUP.md](OPENCODE_SETUP.md)** — Connect OpenCode, configure MCP, model setup, full tool reference
- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Architecture, tech stack, development workflow
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Debugging and crash recovery
