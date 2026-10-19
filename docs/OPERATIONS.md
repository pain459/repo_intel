# Operations Guide

Day-to-day operations for running repo_intel.

## Container Services

Three Docker containers make up the stack:

| Service | Image | Port | Health Check |
|---------|-------|------|-------------|
| `api` | Built from Dockerfile | 8765 (localhost) | `GET /health/live` |
| `worker` | Built from Dockerfile | — | — (long-running) |
| `postgres` | `pgvector/pgvector:pg16` | 5432 (internal) | `pg_isready` |

Data persists in the named volume `repo_intel_pgdata`.

## Startup

```bash
docker compose up -d --build
```

Wait ~15 seconds for both postgres and api to become healthy.

### Verify Everything Is Up

```bash
# Container status
docker compose ps

# Health endpoints
curl http://localhost:8765/health/live    # {"status":"ok"}
curl http://localhost:8765/health/ready   # {"status":"ok","database":"ok","ollama":"ok"}

# Diagnostics (DB + Ollama)
docker compose exec api repo-intel doctor
```

### Expected doctor output

```
Check                 Status   Detail
────────────────────  ────────  ─────────────────────────────
Environment configured  PASS    profile=remote-ollama, host=0.0.0.0:8765
PostgreSQL reachable    PASS    connected
Ollama reachable        PASS    ok, models: nomic-embed-text, qwen3.6:27b
Embedding model ...     PASS    model=nomic-embed-text (verified)
Network: Ollama DNS     PASS    resolves to 192.168.68.62
```

## Shutdown

```bash
docker compose down
```

Use `docker compose down -v` only when you want to **wipe** the PostgreSQL volume (all indexed data, memories, and checkpoints will be lost).

## Rebuild After Code Changes

```bash
docker compose up -d --build
```

## Add a Repository

```bash
# Register a repo for indexing
docker compose exec api repo-intel repo add /path/to/repo

# Register with a custom name
docker compose exec api repo-intel repo add --name my-app /path/to/repo

# Trigger indexing
docker compose exec api repo-intel index

# Check status
docker compose exec api repo-intel status
```

### Register a Repo via MCP Tool

From within OpenCode (once connected):

```
Use repo_intel.repo_list to see what's registered.
Register via REST: POST /api/repositories/ with {"path": "/path/to/repo", "name": "my-repo"}
```

### Register a Repo Using OpenCode Tools Directly

The `repo_list` MCP tool shows registered repos. Use the REST API to register:

```bash
curl -X POST http://localhost:8765/api/repositories/ \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/repo", "name": "my-repo"}'
```

## Mount New Repositories

To index a new repository, add a volume mount in `compose.yaml` and rebuild:

```yaml
volumes:
  - /path/on/host:/repos/my-new-repo:ro
```

Then register via CLI or REST API and trigger indexing.

## Database Backups

### Manual Backup

```bash
docker compose exec postgres pg_dump -U repo_intel repo_intel > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
docker compose exec -T postgres pg_restore -U repo_intel -d repo_intel < backup_20261019.sql
```

### Volume Backup

```bash
docker run --rm -v repo_intel_pgdata:/data -v $PWD:/backup alpine tar czf /backup/pgdata.tar.gz -C /data .
```

## Logs

```bash
# Follow all logs
docker compose logs -f

# Just the API
docker compose logs -f api

# Just the worker
docker compose logs -f worker

# Last N lines
docker compose logs --tail=50 api
```

## Common Commands Reference

| Task | Command |
|------|---------|
| Start stack | `docker compose up -d --build` |
| Stop stack | `docker compose down` |
| Rebuild | `docker compose up -d --build` |
| Run tests | `docker compose exec api pytest tests/ -v` |
| Run lint | `docker compose exec api ruff check src/ tests/` |
| Run diagnostics | `docker compose exec api repo-intel doctor` |
| Register repo | `docker compose exec api repo-intel repo add /path` |
| Re-index all | `docker compose exec api repo-intel index` |
| Shell into API | `docker compose exec api bash` |
| Shell into Postgres | `docker compose exec postgres psql -U repo_intel repo_intel` |
| Apply migrations | `docker compose exec api alembic upgrade head` |
| Check migration status | `docker compose exec api alembic current` |
| Follow logs | `docker compose logs -f` |
