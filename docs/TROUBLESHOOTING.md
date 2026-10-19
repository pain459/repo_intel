# Troubleshooting

Common issues, debugging steps, and emergency recovery procedures.

---

## Quick Diagnostics

Run these first when something isn't working:

```bash
# Overall system health
docker compose exec api repo-intel doctor

# Container status
docker compose ps

# Service health endpoints
curl http://localhost:8765/health/live
curl http://localhost:8765/health/ready

# Recent logs
docker compose logs --tail=50 api
docker compose logs --tail=50 worker
docker compose logs --tail=20 postgres
```

---

## Container Issues

### Containers Won't Start

```bash
# Check which service fails
docker compose ps
docker compose logs <service_name>

# Port conflict
lsof -i :8765

# Disk space full (Docker)
df -h /var/lib/docker
docker system df
```

### API Crashes on Startup

Common causes:

1. **Missing `.env`** → `cp .env.example .env`, fill in required values
2. **Bad `DATABASE_URL`** → password must match `POSTGRES_PASSWORD`
3. **Postgres not ready** → wait for health check, `docker compose ps` shows healthy
4. **Ollama unreachable** → check `OLLAMA_BASE_URL` in `.env`

Check logs:
```bash
docker compose logs api | tail -50
```

### PostgreSQL Lock File

If postgres fails with `FATAL: lock file exists`:

```bash
docker compose down -v   # ⚠️ wipes all data
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Only use `-v` after backing up or if the data is expendable.

---

## Indexing Problems

### Repo Shows as `pending` or `stale`

```bash
# Check worker is running
docker compose ps worker
docker compose logs worker | tail -30

# Manual index
docker compose exec api repo-intel index --repo-path /workspace/my-project

# Check the repo path is accessible inside the container
docker compose exec api ls -la /workspace/
```

### "Repository path not found"

The path in `--path` must exist inside the Docker container. Host paths are mounted via `compose.yaml` volumes. Verify:

```bash
docker compose exec api ls /workspace/
docker compose exec api ls /repos/
```

### Worker Crashes (SQLAlchemy greenlet error)

This was fixed in v1.0. If it reappears, rebuild:

```bash
docker compose up -d --build
```

### Index Seems Stuck

```bash
# Force re-index
docker compose exec api repo-intel index --repo-path /workspace/my-project

# Check for large files (MAX_FILE_BYTES default 1MB)
find /path/to/repo -size +1M -type f
```

---

## Search Issues

### Zero Results

```bash
# 1. Is the repo indexed?
docker compose exec api repo-intel status

# 2. Check chunk count in DB
docker compose exec api psql -U repo_intel -d repo_intel -c "SELECT count(*) FROM index_chunks;"

# 3. Try a simpler query
docker compose exec api repo-intel search "import"

# 4. Check Ollama is responding (semantic search requires it)
curl http://localhost:8765/health/ready
```

### Slow Queries

Check Grafana dashboard at `http://localhost:3000` → Search Performance section. Look at the latency histogram. P95 > 2s warrants investigation:

```bash
# Check embedding dimension (should be 768 for nomic-embed-text)
docker compose exec api psql -U repo_intel -d repo_intel -c "SELECT vector_dims FROM index_chunks LIMIT 1;"

# Check index counts
docker compose exec api psql -U repo_intel -d repo_intel -c "SELECT repository_id, count(*) FROM index_chunks GROUP BY repository_id;"
```

---

## MCP / OpenCode Issues

### Tools Not Appearing in OpenCode

1. Verify MCP server is reachable:
   ```bash
   curl http://localhost:8765/mcp/ -X POST -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}'
   ```
2. Check OpenCode config (`opencode.jsonc`) points to correct URL
3. Rebuild containers: `docker compose up -d --build`

### "MCP server could not be mounted"

`fastmcp` package not installed. Rebuild:

```bash
docker compose up -d --build
docker compose logs api | grep -i fastmcp
```

### Tool Calls Time Out

Check if the worker is consuming all resources:

```bash
docker stats --no-stream
```

If memory is maxed out, increase limits in `compose.yaml` or reduce `EMBEDDING_BATCH_SIZE` in `.env`.

---

## Database Issues

### Connection Refused from API

```bash
# Check postgres is healthy
docker compose ps postgres

# Test connection from inside the api container
docker compose exec api python -c "
from repo_intel.db.session import async_session
import asyncio
asyncio.run(async_session().execute('SELECT 1'))
"
```

### Migration Conflicts

```bash
# Check current revision
docker compose exec api alembic current

# Upgrade to latest
docker compose exec api alembic upgrade head

# If migrations are conflicting, check history
docker compose exec api alembic history
```

### Corrupt Data / Recovery

```bash
# Export before any destructive operation
docker compose exec api repo-intel backup --destination /tmp/backup.sql

# Restore from backup
docker compose exec api repo-intel restore --source /tmp/backup.sql
```

---

## Monitoring Issues

### Grafana Shows "No Data"

1. **Prometheus not scraping**: Check Prometheus targets at `http://localhost:9090/targets`. The `api` target should be `UP`.
2. **Not enough time**: Reduce scrape interval in `monitoring/prometheus.yaml` (default 10s) and generate some traffic.
3. **Dashboard not provisioned**: Check Grafana logs: `docker compose logs grafana | tail -20`

### Prometheus Missing Metrics

```bash
# Verify metrics endpoint works
curl http://localhost:8765/metrics | head -20

# From inside the container (if host networking fails on macOS)
docker compose exec api curl -s http://127.0.0.1:8765/metrics | head -20
```

---

## Emergency Recovery

### Full Stack Reset

When everything else fails:

```bash
# Stop and remove containers
docker compose down

# Remove volumes (⚠️ destroys all indexed data)
docker volume rm repo_intel_pgdata repo_intel_promdata repo_intel_grafanadata 2>/dev/null || true

# Rebuild and start fresh
docker compose up -d --build

# Run migrations
docker compose exec api alembic upgrade head

# Re-register repos and re-index
docker compose exec api repo-intel repo add --name "my-project" /workspace/my-project
```

### Container Stuck in Restart Loop

```bash
# Force stop
docker compose stop api worker

# Remove and recreate
docker compose rm -f api worker
docker compose up -d api worker
```

### Out of Disk Space

```bash
# Check Docker disk usage
docker system df

# Prune unused images and volumes
docker system prune -a --volumes   # ⚠️ aggressive, removes stopped containers and dangling images

# Check PostgreSQL volume size
docker volume inspect repo_intel_pgdata
```

### Kill Stale Processes

If something leaves behind processes:

```bash
# Find stale repo-intel processes
ps aux | grep repo-intel | grep -v grep

# Kill if stuck
kill -9 <pid>
```

---

## Getting Help

If none of the above resolves your issue:

1. Collect diagnostics: `docker compose exec api repo-intel doctor`
2. Save logs: `docker compose logs > /tmp/repo-intel-logs.txt`
3. Check GitHub issues: [repo_intel issues](https://github.com/your-org/repo_intel/issues)
4. File a new issue with the diagnostics output and relevant log excerpts
