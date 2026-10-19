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

The path is **inside the container**. Your host repos are mounted via `compose.yaml` volumes.

### Mount Your Repo

If `FLOW` lives at `/Users/ravik/src_git/FLOW` on your Mac, add a volume to `compose.yaml` under the `api` and `worker` services:

```yaml
volumes:
  - /Users/ravik/src_git/FLOW:/repos/FLOW:ro
```

Then restart:

```bash
docker compose up -d
```

### Register It

```bash
docker compose exec api repo-intel repo add --name "FLOW" /repos/FLOW
```

`--name` is optional — without it, repo_intel uses the directory basename.

### List Registered Repos

```bash
docker compose exec api repo-intel repo list
```

### Remove a Repository (if needed)

```bash
docker compose exec api repo-intel repo remove <uuid> --yes
```

Get the UUID from the `repo list` output.

---

## 4. Run the First Index

```bash
# Index a specific repo
docker compose exec api repo-intel index --repo-path /repos/FLOW

# Or index everything
docker compose exec api repo-intel index
```

Or let the worker pick it up automatically (polls every 10 seconds).

### Check Progress

```bash
docker compose exec api repo-intel status
```

---

## 5. Search

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

## 6. Run Diagnostics

```bash
docker compose exec api repo-intel doctor
```

Checks database, Ollama connectivity, environment config. All should pass.

---

## 7. Run the Benchmark

```bash
# All repos
docker compose exec api repo-intel benchmark

# Specific repo
docker compose exec api repo-intel benchmark --repository-id <uuid>
```

---

## 8. Backup and Restore

```bash
# Create a backup (saved to ./backups/)
docker compose exec api repo-intel backup

# Custom output directory
docker compose exec api repo-intel backup --output /tmp/backups

# Restore from a backup file
docker compose exec api repo-intel restore /path/to/repo_intel_db_20260101_120000.sql.gz --yes
```

---

## 9. Configure OpenCode MCP

Generate the OpenCode MCP config automatically:

```bash
docker compose exec api repo-intel mcp configure --client opencode --transport sse
```

Prompts you to confirm, then writes to `~/.config/opencode/mcp.json`.

---

## 10. Verify with MCP Tools

Once OpenCode is configured (see [OPENCODE_SETUP.md](OPENCODE_SETUP.md)), test in Code Mode:

```
# List repos
tools.repo_intel["repo_list"]()

# Search
tools.repo_intel["repo_search"](query="authentication", limit=5)

# Find a symbol
tools.repo_intel["repo_symbol"](symbol_name="authenticate_user")

# Check index status
tools.repo_intel["index_status"](repository_id="<uuid>")
```

---

## What's next?

- **[OPENCODE_SETUP.md](OPENCODE_SETUP.md)** — Connect OpenCode, configure MCP, model setup, full tool reference
- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Architecture, tech stack, development workflow
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Debugging and crash recovery
