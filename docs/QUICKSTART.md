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

Tell repo_intel which local repos to index. The repos must already be mounted into the Docker containers via `compose.yaml` volumes.

```bash
docker compose exec api repo-intel repo add \
  --name "my-project" \
  --path /workspace/my-project \
  --language python
```

> **Note:** `/workspace` inside the container maps to whatever host directory you set `HOST_REPO_ROOT=` to in compose. Adjust the `--path` accordingly.

Verify it registered:

```bash
docker compose exec api repo-intel repo list
```

---

## 4. Run the First Index

```bash
docker compose exec api repo-intel index --repository-id <uuid-from-above>
```

Or let the worker pick it up automatically. The worker polls every 10 seconds (configurable via `INDEX_POLL_SECONDS`) and indexes any unindexed or modified repos.

Check progress:

```bash
docker compose exec api repo-intel status
```

---

## 5. Search

### From the CLI

```bash
docker compose exec api repo-intel search \
  --query "how does authentication work" \
  --repository-id <uuid>
```

### Via the API

```bash
curl -X POST http://localhost:8765/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how does authentication work", "limit": 10}'
```

### From OpenCode (MCP Tools)

Once configured, use any of the 17 MCP tools directly in Code Mode:

```
tools.repo_intel["repo_search"](query="authentication flow", repository_id="<uuid>")
tools.repo_intel["repo_symbol"](symbol_name="authenticate_user")
tools.repo_intel["repo_dependencies"](symbol_name="authenticate_user", direction="outgoing")
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full MCP tool list and connection setup.

---

## 6. Verify with Doctor

```bash
docker compose exec api repo-intel doctor
```

This checks database connectivity, Ollama availability, repository status, and index health. Every check should report `OK`.

---

## 7. Optional — Run the Benchmark

```bash
docker compose exec api repo-intel benchmark
```

Runs 10 predefined queries and reports recall, latency, and coverage metrics.

---

## What's next?

- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Architecture, tech stack, development workflow
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Debugging and crash recovery
