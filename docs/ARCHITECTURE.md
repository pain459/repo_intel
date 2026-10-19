# Architecture

High-level design and data-flow diagrams for repo_intel.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         OpenCode Agent                          │
│                                                                 │
│  Code Mode execute → tools.repo_intel.*                         │
│ (opencode.jsonc configures MCP server URL)                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ MCP Streamable HTTP (JSON-RPC 2.0)
                           │ POST /mcp/
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Docker Stack                              │
│                                                                 │
│  ┌────────────────────┐    ┌──────────────────────────────────┐ │
│  │   api (FastAPI)    │    │          worker (Celery-like)     │ │
│  │  :8765             │    │  (background indexing jobs)       │ │
│  │                    │    │                                  │ │
│  │  /health/*         │    │  ┌──────────────────────────┐    │ │
│  │  /mcp/ ← FastMCP   │    │  │  Index Pipeline          │    │ │
│  │  /api/* ← REST     │    │  │  discovery → chunk → emb  │    │ │
│  │  /health/*         │    │  └──────────────────────────┘    │ │
│  │  /metrics          │    │                                  │ │
│  └────────┬───────────┘    └──────────────┬───────────────────┘ │
│           │                               │                     │
│           └─────────────┬─────────────────┘                     │
│                         │                                       │
│           ┌─────────────▼─────────────────┐                     │
│           │   postgres:5432 (pgvector)     │                     │
│           │                                │                     │
│           │  repositories | chunks |       │                     │
│           │  index_generations | index_jobs │                     │
│           │  agent_memory | checkpoints    │                     │
│           └────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
                           │
            HTTP (embedding requests)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Remote Ollama (192.168.68.62:11434)                            │
│                                                                 │
│  nomic-embed-text → 768-dim vectors                             │
└─────────────────────────────────────────────────────────────────┘
```

## Component Map

| Component | Module | Responsibility |
|-----------|--------|----------------|
| **CLI** | `cli.py` | Entry point for `repo-intel` commands (serve, index, repo add, doctor, status) |
| **Config** | `config.py` | Settings from env vars / `.env` (profile, DB URL, Ollama, indexing params) |
| **FastAPI App** | `api/app.py` | ASGI factory, lifespan (DB connect/disconnect), mounts `/mcp/`, `/api/`, `/health/`, `/workspace/` |
| **MCP Server** | `mcp/fastmcp.py` | FastMCP server with 14 async tool handlers → calls service-layer functions |
| **Compaction** | `compaction/manager.py` | Auto-checkpoint scheduler, stale invalidation, session bootstrap |
| **REST MCP Proxy** | `api/mcp.py` | Legacy `POST /api/mcp/call` for non-MCP clients |
| **Search API** | `api/search.py` | REST search endpoints |
| **Memory API** | `api/memory.py` | REST CRUD for agent memories |
| **Checkpoint API** | `api/checkpoints.py` | REST CRUD for session checkpoints |
| **Repository API** | `api/repositories.py` | REST for repo registration |
| **Health** | `api/health.py` | `/health/live` and `/health/ready` |
| **Database** | `db/models.py`, `db/session.py` | SQLAlchemy async models, engine, session factory, migration support |
| **Indexing** | `indexing/` | File discovery, text chunking, embedding generation |
| **Retrieval** | `retrieval/search.py` | Hybrid search: exact + FTS + vector cosine, RRF fusion |
| **Memory** | `memory/` | Agent memory models and lifecycle (candidate → verified/superseded/rejected) |

## Data Models

```
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│  repositories    │───┐   │  index_generations│    ┌─▶│   index_jobs     │
│──────────────────│   │   │──────────────────│    │  │──────────────────│
│ id (PK)         │   │   │ id (PK)          │    │  │ id (PK)          │
│ name            │   │   │ repository_id(FK)│────┘  │ repository_id(FK) │
│ path            │   │   │ chunk_count      │    │  │ job_type         │
│ status          │   │   │ embedding_model  │    │  │ status           │
│ indexed_at      │   │   │ created_at       │    │  │ started_at       │
└────────┬────────┘   │   └──────────────────┘    │  │ completed_at     │
         │            │                           │  └──────────────────┘
         │            │   ┌──────────────────┐    │
         │            └──▶│     chunks       │◀───┘
         │               │──────────────────│
         │               │ id (PK)          │
         │               │ repository_id(FK)│
         │               │ file_path        │
         │               │ start_line       │
         │               │ end_line         │
         │               │ text             │
         │               │ embedding(768)   │ ◀── pgvector halfvec
         │               │ token_count      │
         │               │ generation_id(FK)│
         │               └──────────────────┘
         │
         │               ┌──────────────────┐
         ├───────────────│   agent_memory   │
         │               │──────────────────│
         │               │ id (PK)          │
         │               │ repository_id(FK)│ (NULL = global)
         │               │ kind             │ preference|observation|instruction|pattern
         │               │ statement        │ TEXT
         │               │ status           │ candidate|verified|superseded|rejected
         │               │ evidence         │ JSONB
         │               │ source_commit    │
         │               │ created_at       │
         │               └──────────────────┘
         │
         │               ┌──────────────────┐
         └───────────────│  checkpoints     │
                         │──────────────────│
                         │ id (PK)          │
                         │ repository_id(FK)│ (NULL = global)
                         │ session_id       │
                         │ objective        │
                         │ current_state    │
                         │ changed_files    │ TEXT[]
                         │ pending_steps    │ TEXT[]
                         │ evidence         │ JSONB
                         │ created_at       │
                         └──────────────────┘
```

## Indexing Pipeline

```
repo-intel index
      │
      ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  discover   │────▶│    chunk         │────▶│  embed batches  │
│  files      │     │    text         │     │  (→ Ollama)     │
│             │     │                 │     │                 │
│ git ls-files│     │ 200-line windows│     │ batch_size=16   │
│ + filter    │     │ 20% overlap     │     │ POST /api/embed │
│ extensions  │     │ + file header   │     │                 │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                         ┌─────────────────────────────┘
                         ▼
               ┌──────────────────┐     ┌──────────────────┐
               │  upsert chunks   │────▶│  update gen &    │
               │  to PostgreSQL   │     │  repo metadata   │
               │  (ON CONFLICT   │     │                  │
               │  DO UPDATE)     │     │  index_jobs       │
               │                │     │  → completed       │
               └────────────────┘     └──────────────────┘
```

**In production**, the `index` command creates an `index_job` record and the worker container polls for pending jobs, executing the same pipeline asynchronously.

## Search Pipeline (Hybrid Retrieval)

```
repo_search(query="how does auth work", limit=10)
      │
      ├──► 1. Exact Match (SQL LIKE on file_path, text)
      │         │
      │         ▼
      │     up to 5 results
      │
      ├──► 2. Full-Text Search (PostgreSQL tsvector @@ plainto_tsquery)
      │         │
      │         ▼
      │     top 10 results ranked by ts_rank
      │
      └──► 3. Semantic Vector Search (Ollama embeds query → cosine similarity)
                │ cos_distance(chunks.embedding, query_vector)
                │
                ▼
            top 10 results ranked by vector similarity
                      │
                      ▼
            ┌─────────────────────┐
            │  RRF Fusion (K=60)  │
            │  rank = Σ 1/(K+r_i) │
            │  deduplicate by     │
            │  chunk id           │
            └────────┬────────────┘
                     ▼
              sorted by fused score
                     ▼
              return top N (default 10)
```

### RRF (Reciprocal Rank Fusion)

Each retrieval method returns a ranked list. For each document `d`:

```
score(d) = Σ 1 / (K + rank_method(d))
```

where `K = 60` (standard RRF constant). Documents appearing in multiple result sets get boosted.

## MCP Tool Flow

```
OpenCode Code Mode
      │
      │ tools.repo_intel.repo_search(...)
      │
      ▼
┌───────────────────────────────────────────────┐
│  MCP Client (FastMCP, built into OpenCode)     │
│                                               │
│  POST /mcp/                                   │
│  { jsonrpc: "2.0",                            │
│    id: 42,                                    │
│    method: "tools/call",                      │
│    params: {                                  │
│      name: "repo_search",                     │
│      arguments: { query: "...", ... }         │
│    }                                          │
│  }                                            │
└──────────────────┬────────────────────────────┘
                   │
                   ▼
        ┌────────────────────┐
        │  FastMCP Router    │
        │  (mounted at /mcp) │
        └────────┬───────────┘
                 │
                 ▼
        ┌────────────────────┐
        │  @mcp_tool handler │
        │  (in fastmcp.py)   │
        │                    │
        │  Calls service     │
        │  layer function    │
        └────────┬───────────┘
                 │
        ┌────────▼───────────┐
        │  Service Layer     │
        │  (search, memory,  │
        │   indexing, etc.)  │
        └────────┬───────────┘
                 │
        ┌────────▼───────────┐
        │  PostgreSQL        │
        │  (+ pgvector)      │
        └────────────────────┘
```

## Memory Lifecycle

```
              ┌──────────┐
              │ Write    │
              │ memory   │
              └────┬─────┘
                   │
                   ▼
            ┌─────────────┐
            │  candidate   │◀─── default initial state
            └──────┬──────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌────────┐ ┌──────────┐ ┌──────────┐
   │verified│ │superseded│ │ rejected │
   │        │ │(replaced)│ │(wrong)   │
   └────────┘ └──────────┘ └──────────┘
                   │
                   ▼
            ┌─────────────┐
            │ new memory   │─── replaces superseded entry
            │ written      │
            └─────────────┘
```

## Session Checkpoint Flow

```
Agent starts session
      │
      ▼
┌──────────────────┐
│ checkpoint_save  │  ← every 15-20 min, or on milestone
│ (objective,      │
│  session_id,     │
│  state, files,   │
│  pending steps)  │
└────────┬─────────┘
         │
         ▼
  ┌──────────────────┐
  │ UPSERT into      │
  │ checkpoints      │
  │ (latest per      │
  │  session+repo)   │
  └──────────────────┘

  ┌──────────────────┐
  │ Session ends or  │
  │ agent interrupted│
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ checkpoint_get   │  ← on session resume
  │ (session_id,     │
  │  repository_id)  │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │ Returns latest   │
  │ checkpoint row   │
  │ → agent restores │
  │ context          │
  └──────────────────┘
```

## Compaction Continuity

```
AutoCheckpointScheduler (in API container)
       │
       │ Every 15 min (configurable)
       ▼
┌─────────────────────┐
│ Scan checkpoints    │  ← find checkpoints > 4 hours old
│ older than threshold │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Mark stale in        │  ← evidence.compaction.marked_stale_at
│ evidence dict       │
└─────────────────────┘

Agent before compaction:
   └──► compaction_checkpoint_save(objective, session_id, ...)
                 │
                 ▼
        ┌─────────────────┐
        │ Tag with        │
        │ compaction mark │  ← evidence.compaction.save_type="pre_compaction"
        └─────────────────┘

Agent after compaction/restart:
   └──► session_bootstrap(session_id, repository_id)
                 │
                 ▼
        ┌───────────────────────────────┐
        │ Return:                       │
        │  • Latest checkpoint           │
        │  • Up to 20 verified memories  │
        │  • Scoped to session/repo      │
        └───────────────────────────────┘
```

**Design notes:**
- No OpenCode lifecycle hooks required (unreliable, version-dependent)
- Auto-checkpoint scheduler runs as a background task in the API container
- Stale checkpoints are marked in `evidence.compaction`, not deleted
- Agents call `compaction_checkpoint_save` explicitly before compaction
- Agents call `session_bootstrap` to reconstruct context after compaction

## Dependency Graph

```
Symbol ──► SymbolEdge ──► Symbol
(from)     (relation)    (to)

Relation types: "imports", "calls", "extends", "uses"
Confidence: 0.0 – 1.0 (heuristic)
Evidence: source file, line numbers

During indexing:
   edge_detector scans Python/JS import and call patterns → writes to symbol_edges

During search:
   repo_dependencies MCP tool performs BFS traversal (bounded depth, max 50 edges)
```

## Directory Structure

```
repo_intel/
├── compose.yaml              # Docker services (api, worker, postgres)
├── Dockerfile                # Python 3.12 + pip + uvicorn
├── requirements.txt          # All Python dependencies
├── alembic.ini / alembic/    # DB migration config + scripts
├── docs/
│   ├── OPERATIONS.md         # Day-to-day operations
│   ├── USAGE.md              # How to use MCP tools, workflows
│   ├── TROUBLESHOOTING.md    # Fix common issues
│   └── ARCHITECTURE.md       # This file
├── opencode.jsonc.example    # MCP server config template
├── src/repo_intel/
│   ├── cli.py                # repo-intel CLI (click commands)
│   ├── config.py             # Settings from env
│   ├── types.py              # Shared dataclasses
│   ├── api/                  # FastAPI endpoints
│   │   ├── app.py            # Factory, lifespan, route mounting
│   │   ├── health.py         # /health/live, /health/ready
│   │   ├── metrics.py        # /metrics (Prometheus)
│   │   ├── mcp.py            # REST MCP proxy (POST /api/mcp/call)
│   │   ├── search.py         # REST search
│   │   ├── memory.py         # REST memory CRUD
│   │   ├── checkpoints.py    # REST checkpoint CRUD
│   │   └── repositories.py   # REST repo registration
│   ├── compaction/           # Compaction continuity (Phase 5)
│   │   └── manager.py        # AutoCheckpointScheduler, session_bootstrap
│   ├── mcp/                  # MCP protocol
│   │   ├── fastmcp.py        # FastMCP server, 14 async tool handlers
│   │   └── server.py         # Tool implementations (used by REST proxy)
│   ├── db/                   # Database layer
│   │   ├── models.py         # SQLAlchemy async models
│   │   └── session.py        # Engine, async session factory
│   ├── indexing/             # Indexing pipeline
│   │   ├── indexer.py        # Orchestration (discover → chunk → embed)
│   │   ├── discovery.py      # git ls-files + extension filter
│   │   ├── chunker.py        # 200-line windows, 20% overlap
│   │   ├── edge_detector.py  # Heuristic import/call edge detection
│   │   ├── embeddings/       # Embedding generation (calls Ollama)
│   │   └── symbols/          # AST-based symbol extraction
│   ├── retrieval/            # Search & retrieval
│   │   ├── search.py         # Hybrid search pipeline (exact+FTS+vector, RRF)
│   │   └── types.py          # Result dataclasses
│   ├── benchmark/            # Retrieval quality benchmarks
│   │   └── runner.py         # Benchmark runner (10 default queries)
│   ├── memory/               # Agent memory
│   │   └── (models + lifecycle in db/models.py)
│   └── security/             # Security
│       ├── redaction.py      # Content redaction (secrets, API keys)
│       └── prompt_guard.py   # Prompt-injection defense
└── tests/                    # pytest test suite (154 tests)
```

## Technology Stack

| Layer | Technology | Version / Detail |
|-------|-----------|------------------|
| Language | Python | 3.12 |
| Web Framework | FastAPI | async ASGI, lifespan |
| MCP Transport | fastmcp | 2.14.7 (Streamable HTTP) |
| Database | PostgreSQL + pgvector | pg16, halfvec(768) |
| ORM | SQLAlchemy | 2.x async (psycopg) |
| Migrations | Alembic | autogenerate |
| Embeddings | Ollama (remote) | nomic-embed-text → 768-dim |
| Container | Docker Compose | api, worker, postgres services |
| Hosting | localhost | 127.0.0.1:8765 |
| Embedding dimension | 768 | matches nomic-embed-text |
