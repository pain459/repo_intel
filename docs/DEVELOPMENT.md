# Development Guide

Development workflow, testing, migrations, and monitoring for repo_intel.

> **For full architecture details** (HLD, LLD, data model, request flows, memory system), see **[docs/ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Technology Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| Framework | FastAPI (async), Uvicorn |
| ORM | SQLAlchemy 2.0 (async), Alembic migrations |
| Database | PostgreSQL 16 + pgvector extension |
| Embeddings | Ollama (`nomic-embed-text`) |
| MCP server | fastmcp >= 2.3.1 |
| CLI | Typer + Rich |
| Structured logging | structlog |
| Testing | pytest + pytest-asyncio |
| Code quality | ruff |
| Containerization | Docker Compose |
| Monitoring | Prometheus + Grafana |
| Packaging | setuptools, pyproject.toml |

---

## Development Workflow

### Run Tests

```bash
docker compose exec api pytest tests/
```

All 154 tests should pass. Lint check:

```bash
docker compose exec api ruff check src/ tests/
```

### Database Migrations

```bash
# Generate a new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply pending migrations
docker compose exec api alembic upgrade head

# Check current state
docker compose exec api alembic current
```

### Add a New MCP Tool

1. Define the function in `src/repo_intel/mcp/fastmcp.py`
2. Decorate with `@_instrument_tool` for metrics
3. Add tests in `tests/`
4. Run `pytest tests/` and `ruff check`

### Monitoring

- **Prometheus**: `http://localhost:9090`
- **Grafana**: `http://localhost:3000` (admin / admin)
- **Metrics endpoint**: `http://localhost:8765/metrics`

The dashboard has 6 sections: overview, search performance, MCP tool calls, database health, worker status, and resource usage.

---

## Docker Volume Cleanup

The PostgreSQL data volume is `repo_intel_pgdata`. To reset:

```bash
docker compose down -v   # ⚠️ destroys all indexed data
docker compose up -d --build
docker compose exec api alembic upgrade head
```

Only do this in development. Always export before destroying volumes in production.

---

## Related

- [QUICKSTART.md](QUICKSTART.md) — Step-by-step setup for new users
- [ARCHITECTURE.md](ARCHITECTURE.md) — HLD, LLD, request flows, data model, memory system
- [OPENCODE_SETUP.md](OPENCODE_SETUP.md) — Connect OpenCode, configure MCP
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Debugging and crash recovery
