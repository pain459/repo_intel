# Troubleshooting Guide

Common issues and how to resolve them.

## Container Issues

### Containers Won't Start

```bash
# Check what's failing
docker compose ps
docker compose logs

# Check port conflict
lsof -i :8765

# Check disk space
df -h /var/lib/docker
```

### PostgreSQL Volume Lock

If postgres fails with "FATAL: lock file exists":

```bash
docker compose down -v  # ⚠️ wipes all data
docker compose up -d --build
docker compose exec api alembic upgrade head
```

**Warning:** `-v` destroys the PostgreSQL volume. Only use after backing up.

### API Container Crashes on Startup

```bash
# Check logs for the error
docker compose logs api | tail -50

# Common causes:
# 1. Missing .env file → cp .env.example .env
# 2. Bad DATABASE_URL → check .env
# 3. Postgres not ready → wait for health check
```

### "MCP server could not be mounted" Warning

This means `fastmcp` is not installed. Rebuild:

```bash
docker compose up -d --build
```

Verify in logs:
```
MCP server mounted at /mcp
```

## Database Issues

### Alembic Migration Errors

```bash
# Check current migration
docker compose exec api alembic current

# Re-apply migrations
docker compose exec api alembic upgrade head
```

### "relation does not exist" Errors

After a migration, tables may not exist yet:

```bash
docker compose exec api alembic upgrade head
```

### Connection Refused to PostgreSQL

```bash
# Check postgres is running
docker compose ps postgres

# Check postgres health
docker compose logs postgres | tail -20

# Test connection manually
docker compose exec api python -c "
from repo_intel.db.session import get_engine
print(get_engine())
"
```

## Ollama / Embedding Issues

### "Ollama not reachable" in doctor

```bash
# Check Ollama is running
curl http://192.168.68.62:11434/api/tags

# Check network connectivity
ping -c 2 192.168.68.62

# Check Ollama model is loaded
curl http://192.168.68.62:11434/api/pull -d '{"name": "nomic-embed-text"}'
```

### Search Returns Few Results

```bash
# Check if repos are actually indexed with embeddings
docker compose exec postgres psql -U repo_intel repo_intel -c "
SELECT r.name,
       count(DISTINCT c.id) AS chunks,
       count(DISTINCT c.id) FILTER (WHERE c.embedding IS NOT NULL) AS with_embeddings
FROM repositories r
LEFT JOIN chunks c ON c.repository_id = r.id
GROUP BY r.name;
"
```

If `with_embeddings` is 0, trigger re-indexing:

```bash
docker compose exec api repo-intel index
```

## MCP Endpoint Issues

### "Session ID missing" Error

The MCP endpoint uses session-based Streamable HTTP. Each client needs to:

1. Call `initialize` first
2. Use the `Mcp-Session-Id` header in subsequent requests

OpenCode handles this automatically. If testing manually:

```bash
# Step 1: Initialize
RESP=$(curl -s -D- http://localhost:8765/mcp/ \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream, */*" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"test","version":"1.0"}}}')

SESSION=$(echo "$RESP" | grep -i "Mcp-Session-Id" | awk '{print $2}' | tr -d '\r')

# Step 2: Use session
curl http://localhost:8765/mcp/ \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream, */*" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

### OpenCode Doesn't Discover Tools

1. Check `opencode.jsonc` exists and points to correct URL:
   ```jsonc
   {
     "mcp": {
       "servers": {
         "repo_intel": {
           "type": "remote",
           "url": "http://localhost:8765/mcp/"
         }
       }
     }
   }
   ```

2. Verify the MCP endpoint is up:
   ```bash
   curl -sf http://localhost:8765/health/live
   ```

3. Check OpenCode logs / MCP connection status

## Indexing Issues

### Worker Not Processing Jobs

```bash
# Check worker is running
docker compose ps worker

# Check for pending jobs
docker compose exec postgres psql -U repo_intel repo_intel -c "
SELECT id, repository_id, job_type, status, created_at
FROM index_jobs
WHERE status IN ('pending', 'running')
ORDER BY created_at DESC
LIMIT 5;
"

# Restart worker
docker compose restart worker
```

### Indexing a New Repo Shows 0 Chunks

The repo needs to be registered first, then indexed:

```bash
# 1. Register
docker compose exec api repo-intel repo add /path/to/repo

# 2. Trigger index
docker compose exec api repo-intel index

# 3. Wait for worker (~30s-2min depending on repo size)
docker compose exec api repo-intel status
```

### High Memory Usage During Indexing

Large repos (>10k files) may consume significant RAM during embedding. Increase container memory limits in `compose.yaml`:

```yaml
services:
  worker:
    deploy:
      resources:
        limits:
          memory: 4G
```

## Monitoring Issues

### "Where are the Prometheus metrics?"

repo_intel exposes a `/metrics` endpoint (Prometheus format) on the API server.
It does **not** include a Prometheus container. Add your own scraper:

```yaml
# prometheus.yaml
scrape_configs:
  - job_name: "repo_intel"
    scrape_interval: 15s
    static_configs:
      - targets: ["your-host:8765"]
    metrics_path: "/metrics"
```

Custom metrics: `repo_intel_search_requests_total`, `repo_intel_search_latency_seconds`,
`repo_intel_index_chunks_total`. Standard Python metrics are also included.

### "Worker shows no tick count"

The worker is healthy even without ticks if there are no pending jobs:

```bash
# Check for pending jobs
docker compose exec postgres psql -U repo_intel repo_intel -c \
  "SELECT count(*) FROM index_jobs WHERE status='pending';"
# 0 = worker is idle (healthy)
```

### "API logs show 'marked stale' but no compaction occurred"

That's normal. The AutoCheckpointScheduler runs every 15 minutes and marks old
checkpoints stale. This is preventive maintenance, not an error.

---

## Performance Issues

### Slow Search Queries (>5 seconds)

```bash
# Check vector index exists
docker compose exec postgres psql -U repo_intel repo_intel -c "
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'chunks';
"

# If missing, recreate indexes
docker compose exec api alembic upgrade head
```

### Slow Embedding Generation

The bottleneck is the Ollama endpoint. Check:
- Ollama server load (`htop` on 192.168.68.62)
- Network latency (`ping 192.168.68.62`)
- Embedding batch size (increase `EMBEDDING_BATCH_SIZE` in .env)

## Emergency Procedures

### Complete Stack Reset

```bash
# 1. Backup database
docker compose exec postgres pg_dump -U repo_intel repo_intel > backup.sql

# 2. Stop everything
docker compose down -v

# 3. Clean Docker images
docker image prune -f

# 4. Restart fresh
docker compose up -d --build
docker compose exec api alembic upgrade head

# 5. Restore if needed
cat backup.sql | docker compose exec -T postgres psql -U repo_intel repo_intel
```

### Recover from Corrupted Volume

```bash
# 1. Stop containers
docker compose down

# 2. Inspect volume
docker volume inspect repo_intel_pgdata

# 3. Remove corrupted volume
docker volume rm repo_intel_pgdata

# 4. Start fresh (data will be re-indexed)
docker compose up -d --build
docker compose exec api alembic upgrade head

# 5. Re-register and re-index all repos
docker compose exec api repo-intel repo add /repos/agent-memory
docker compose exec api repo-intel repo add /repos/rea
docker compose exec api repo-intel index
```

### Quick Health Checklist

```bash
# 1. Containers running
docker compose ps

# 2. Health checks passing
curl http://localhost:8765/health/ready

# 3. Diagnostics
docker compose exec api repo-intel doctor

# 4. Database accessible
docker compose exec postgres pg_isready -U repo_intel

# 5. Ollama reachable
curl http://192.168.68.62:11434/api/tags

# 6. MCP endpoint works
curl -X POST http://localhost:8765/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream, */*" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"test","version":"1.0"}}}' \
  --max-time 5 | grep -q "repo_intel" && echo "MCP OK" || echo "MCP FAIL"
```
