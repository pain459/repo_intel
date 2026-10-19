# Operations Guide

Day-to-day operations for running repo_intel.

## Container Services

Three Docker containers make up the stack:

| Service | Image | Port | Health Check |
|---------|-------|------|-------------|
| `api` | Built from Dockerfile | 8765 (localhost) | `GET /health/live` |
| `worker` | Built from Dockerfile | — | Long-running, logs show tick count |
| `postgres` | `pgvector/pgvector:pg16` | 5432 (internal) | `pg_isready` |

Data persists in the named volume `repo_intel_pgdata`.

---

## Startup

```bash
docker compose up -d --build
```

Wait ~15 seconds for postgres and api to become healthy.

### Verify Everything Is Up

```bash
docker compose ps
curl http://localhost:8765/health/live    # {"status":"ok"}
curl http://localhost:8765/health/ready   # {"status":"ok","database":"ok","ollama":"ok"}
docker compose exec api repo-intel doctor
```

---

## Monitoring

### Health Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `GET /health/live` | Liveness probe | `{"status":"ok"}` |
| `GET /health/ready` | Readiness (DB + Ollama) | `{"status":"ok","database":"ok","ollama":"ok"}` |

### Prometheus Metrics

The API exposes a Prometheus-format `/metrics` endpoint:

```bash
curl http://localhost:8765/metrics
```

**Custom metrics:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `repo_intel_search_requests_total` | counter | `method` | Search requests by method |
| `repo_intel_search_latency_seconds` | histogram | — | Query latency distribution |
| `repo_intel_index_chunks_total` | counter | `chunk_type` | Chunks indexed by type |

**Standard Python metrics:** `python_gc_*`, `process_virtual_memory_bytes`, `process_cpu_seconds_total`, etc.

### Scrape Configuration

To scrape metrics with an external Prometheus instance, add to `prometheus.yaml`:

```yaml
scrape_configs:
  - job_name: "repo_intel"
    scrape_interval: 15s
    static_configs:
      - targets: ["your-host:8765"]
    metrics_path: "/metrics"
```

> **Note:** repo_intel does not ship a Prometheus container. The `/metrics` endpoint is exposed by the FastAPI server. You can run Prometheus separately or use any compatible scraper (Grafana Agent, VictoriaMetrics, etc.).

### Grafana Dashboard (Example)

PromQL queries for a basic dashboard:

```promql
# Search requests per minute
rate(repo_intel_search_requests_total[5m]) * 60

# P95 search latency
histogram_quantile(0.95, rate(repo_intel_search_latency_seconds_bucket[5m]))

# Chunks indexed per minute
rate(repo_intel_index_chunks_total[5m]) * 60

# Process memory
process_resident_memory_bytes
```

### Logs

```bash
# Follow all logs
docker compose logs -f

# Follow a specific service
docker compose logs -f api
docker compose logs -f worker

# Structured JSON logs (set LOG_FORMAT=json in .env)
docker compose logs -f api | jq .

# Last N lines
docker compose logs --tail=50 api
```

### Container Resource Usage

```bash
docker compose stats --no-stream
```

---

## Shutdown

```bash
docker compose down
```

Use `docker compose down -v` only when you want to **wipe** the PostgreSQL volume.

---

## Rebuild After Code Changes

```bash
docker compose up -d --build
```

---

## Add a Repository

```bash
# Via CLI
docker compose exec api repo-intel repo add /path/to/repo
docker compose exec api repo-intel index

# Via MCP (in OpenCode)
tools.repo_intel.repo_list()   # verify

# Via REST
curl -X POST http://localhost:8765/api/repositories/ \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/repo", "name": "my-repo"}'
```

To mount a new repository, add a volume in `compose.yaml` and rebuild.

---

## Background Worker

The worker polls for pending indexing jobs every 10 seconds (configurable via `INDEX_POLL_SECONDS`).

### Worker Health

```bash
# Check worker is running
docker compose ps worker

# Check tick count in logs
docker compose logs worker --tail=5
# Expect: tick=N every 10s
```

The worker is resilient: if an indexing job fails, it marks it as failed and continues polling.

### Compaction Scheduler

The API container runs an **AutoCheckpointScheduler** that:
- Runs every 15 minutes (configurable)
- Marks checkpoints older than 4 hours as stale in their `evidence.compaction` dict
- Logs stale markings to the API logs

---

## Database Maintenance

### Check Schema

```bash
docker compose exec api alembic current
```

### Check Indexes

```bash
docker compose exec postgres psql -U repo_intel repo_intel -c "
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks';"
```

### Check Data Volume

```bash
docker compose exec postgres psql -U repo_intel repo_intel -c "
SELECT
  r.name,
  count(DISTINCT c.id) AS chunks,
  count(DISTINCT c.id) FILTER (WHERE c.embedding IS NOT NULL) AS with_embeddings,
  count(DISTINCT f.id) AS files
FROM repositories r
LEFT JOIN chunks c ON c.repository_id = r.id
LEFT JOIN file_records f ON f.repository_id = r.id
GROUP BY r.name;"
```

---

## Database Backups

### Manual Dump

```bash
docker compose exec postgres pg_dump -U repo_intel repo_intel > backup.sql
```

### Compressed (via CLI)

```bash
docker compose exec api repo-intel backup
```

Stored in `backups/` with timestamp.

### Restore

```bash
docker compose exec api repo-intel restore backups/repo_intel_db_20260101.sql.gz
```

### Volume Backup

```bash
docker run --rm -v repo_intel_pgdata:/data -v $PWD:/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /data .
```

---

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
| Check status | `docker compose exec api repo-intel status` |
| Shell into API | `docker compose exec api bash` |
| Shell into Postgres | `docker compose exec postgres psql -U repo_intel repo_intel` |
| Apply migrations | `docker compose exec api alembic upgrade head` |
| Check migrations | `docker compose exec api alembic current` |
| Follow logs | `docker compose logs -f` |
| Container stats | `docker compose stats --no-stream` |
| Backup | `docker compose exec api repo-intel backup` |
| Restore | `docker compose exec api repo-intel restore <file>` |

---

## Scaling Considerations

### Memory Limits

For large repos (>10k files), increase worker memory in `compose.yaml`:

```yaml
services:
  worker:
    deploy:
      resources:
        limits:
          memory: 4G
```

### Indexing Speed

To speed up indexing:
1. Increase `EMBEDDING_BATCH_SIZE` in `.env` (default: 16)
2. Ensure Ollama server has sufficient GPU/CPU
3. Check network latency to Ollama

### Storage

Index data grows with repo size. Typical density:
- 1 repo with 1000 files → ~15k chunks → ~50MB in PostgreSQL
- Each chunk stores text + 768-dim half-precision vector (~600 bytes)

To free space, remove unused repositories:
```bash
docker compose exec api repo-intel repo remove <uuid>
```
