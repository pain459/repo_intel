# repo_intel

> Persistent, searchable knowledge of Git repositories for coding agents.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-latest-009688)](https://fastapi.tiangolo.com/)
[![PostgreSQL+pgvector](https://img.shields.io/badge/postgres-pgvector-green)](https://github.com/pgvector/pgvector)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-orange)](https://modelcontextprotocol.io/)

---

## What it does

- **Indexes** local Git repositories → searchable chunks in PostgreSQL + pgvector
- **Hybrid search**: exact match + full-text + semantic vector + symbol lookup (4-way RRF fusion)
- **MCP tools**: 14 tools exposed to coding agents (OpenCode) for on-demand retrieval
- **Agent memory**: evidence-backed decisions, preferences, and observations with lifecycle management
- **Session checkpoints**: persist and restore work-in-progress across agent sessions
- **Compaction continuity**: survive context compaction with auto-checkpointing and session bootstrap
- **Monitoring**: Prometheus metrics + Grafana dashboards

---

## Quick start

See **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — clone, configure, start the stack, register a repo, and search in under 5 minutes.

---

## Documentation

| Document | What it covers |
|----------|----------------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Step-by-step setup for new users |
| [docs/OPENCODE_SETUP.md](docs/OPENCODE_SETUP.md) | Connect OpenCode, configure MCP, use tools in Code Mode |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Development workflow |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Debugging, crash recovery, emergency procedures |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | HLD, LLD, request flows, data model, memory system, configuration |

---

## Prerequisites

- Docker + Docker Compose (v2.20+)
- Git
- Access to an Ollama instance with `nomic-embed-text` model (local or remote)

---

## License

MIT
