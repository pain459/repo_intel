# Architecture

Comprehensive High-Level Design (HLD), Low-Level Design (LLD), and flow diagrams for repo_intel.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Design (HLD)](#2-high-level-design-hld)
3. [Low-Level Design (LLD)](#3-low-level-design-lll)
4. [Request Flow Diagrams](#4-request-flow-diagrams)
5. [Data Model](#5-data-model)
6. [Memory System](#6-memory-system)
7. [Checkpoint and Session Persistence](#7-checkpoint-and-session-persistence)
8. [Configuration](#8-configuration)

---

## 1. System Overview

repo_intel is a persistent, searchable knowledge engine for Git repositories. A coding agent (OpenCode) connects via MCP (Model Context Protocol) and submits requests to query, index, and manage repository knowledge. The system maintains vector embeddings, full-text search indices, symbol tables, and dependency graphs in a PostgreSQL database with pgvector.

### Key Properties

- **Hybrid search**: combines exact match, full-text search (FTS), and semantic vector search with Reciprocal Rank Fusion (RRF)
- **Incremental indexing**: content-hash-based change detection; only modified repos are re-indexed
- **Generation tracking**: each index scan creates a new `IndexGeneration`; old generations are marked stale
- **Secret-safe**: content redaction passes chunks through secret-pattern filters before storage
- **Observable**: every search generates a `RetrievalEvent`; Prometheus metrics for latency, throughput, errors

---

## 2. High-Level Design (HLD)

### 2.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Clients                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  OpenCode    │  │  CLI Tool    │  │  HTTP / REST clients     │  │
│  │  (Agent)     │  │  (Typer)     │  │  (curl, SDK, etc.)       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │ MCP/SSE         │ CLI RPC              │ REST JSON         │
└─────────┼─────────────────┼──────────────────────┼───────────────────┘
          │                 │                      │
          ▼                 ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                       API Container (:8765)                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  FastAPI App │  │   FastMCP    │  │   CLI (Typer)         │  │
│  │  (REST API)  │  │  (MCP Tools) │  │  (repo-intel ...)     │  │
│  │              │  │              │  │                       │  │
│  │ - /search/   │  │ - repo_list  │  │ - repo add/list/remove│  │
│  │ - /memory/*  │  │ - repo_      │  │ - index               │  │
│  │ - /api/      │  │   search     │  │ - search              │  │
│  │ - /health    │  │ - repo_      │  │ - status              │  │
│  │ - /metrics   │  │   symbol     │  │ - doctor              │  │
│  └──────┬───────┘  │ - repo_      │  │ - benchmark           │  │
│         │         │   context    │  │ - backup/restore      │  │
│         │         │ - index_     │  │ - mcp configure       │  │
│         │         │   status     │  └───────────────────────┘  │
│         │         │ - memory_*   │                              │
│         │         │ - checkpoint │         ┌─────────────────┐  │
│         │         │ - session    │         │  Retriever      │  │
│         │         │   bootstrap  │         │  (hybrid_search)│  │
│         │         └──────────────┘         └────────┬────────┘  │
│         │                                          │           │
│         │         ┌─────────────────┐               │           │
│         │         │ Retriever       │               │           │
│         └─────────┤ (hybrid_search) │◄──────────────┘           │
│                   └────────┬────────┘                           │
│                            │ SQLAlchemy async                    │
│                   ┌────────▼────────┐                            │
│                   │  DB Session     │                            │
│                   │  (async pool)   │                            │
│                   └────────┬────────┘                            │
└────────────────────────────┼────────────────────────────────────┘
                             │
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
┌──────────────────┐ ┌────────────────┐ ┌──────────────────┐
│  Worker Container│ │  Postgres :5432 │ │  Ollama          │
│  (background)    │ │  (+ pgvector)   │ │  (embeddings)    │
│                  │ │                │ │  :11434           │
│ - polls every   │ │ - repositories │ │                  │
│   10s           │ │ - files        │ │ - nomic-embed-   │
│ - picks up      │ │ - chunks       │ │   text (768d)    │
│   pending jobs  │ │ - symbols      │ │                  │
│ - scans repos   │ │ - memories     │ └──────────────────┘
│ - indexes       │ │ - index_jobs   │
│   on demand     │ │ - checkpoints  │
└─────────────────┘ │ - events       │
                    └────────────────┘
```

### 2.2 Services

| Service | Container | Port | Role |
|---------|-----------|------|------|
| **API** | `api` | 8765 | FastAPI server: REST endpoints, MCP server, CLI commands |
| **Worker** | `worker` | — | Background loop: polls for index jobs, runs scans |
| **PostgreSQL** | `postgres` | 5432 | Primary data store with pgvector for embeddings |
| **Prometheus** | `prometheus` | 9090 | Metrics collector (scrapes `/metrics`) |
| **Grafana** | `grafana` | 3000 | Visualization dashboards |

### 2.3 Technology Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | FastAPI (uvicorn) |
| Protocol | MCP (Streamable HTTP) + REST JSON |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 + pgvector |
| Migrations | Alembic |
| Embeddings | Ollama (`nomic-embed-text`, 768-dimensional) |
| CLI | Typer + Rich |
| Settings | pydantic-settings (`.env`) |
| Containerization | Docker Compose |
| Monitoring | Prometheus client + custom Grafana dashboard |
| Chunking | Pure Python, language-aware boundary detection |

---

## 3. Low-Level Design (LLD)

### 3.1 Directory Structure

```
src/repo_intel/
├── __init__.py
├── api/                        # HTTP/MCP layer
│   ├── app.py                 # FastAPI factory, lifespan, MCP mount
│   ├── health.py              # /health/live, /health/ready
│   ├── metrics.py             # Prometheus metrics definitions + middleware
│   ├── mcp.py                 # MCP transport configuration
│   ├── search.py              # POST /api/search/ endpoint
│   ├── memory.py              # Memory CRUD endpoints
│   ├── repositories.py        # Repository management endpoints
│   └── checkpoints.py         # Checkpoint endpoints
├── cli.py                     # Typer CLI (repo-intel command)
├── config.py                  # pydantic Settings, logging setup
├── db/
│   ├── models.py              # SQLAlchemy ORM models
│   └── session.py             # Async engine + session factory
├── indexing/                  # Indexing pipeline
│   ├── chunker.py             # Language-aware code chunking
│   ├── discovery.py           # File discovery, .gitignore, binary filtering
│   ├── edge_detector.py       # Symbol dependency edge detection
│   ├── indexer.py             # scan_repository(), incremental_scan(), worker_tick()
│   └── embeddings/
│       └── adapter.py         # Ollama embedding client
├── retrieval/                 # Search pipeline
│   ├── search.py              # hybrid_search() — RRF of exact + FTS + vector
│   └── types.py               # SearchRequest, SearchResult dataclasses
├── mcp/
│   └── fastmcp.py             # FastMCP tool definitions (14 tools)
├── compaction/
│   └── manager.py             # Auto-checkpoint scheduling, stale detection
├── benchmark/
│   └── runner.py              # Retrieval quality benchmark suite
├── security/
│   ├── redaction.py           # Secret pattern detection in chunks
│   ├── paths.py               # Path sanitization, secret file detection
│   └── log_filter.py          # Credential redaction in logs
└── context/
    └── builder.py             # Context pack builder for repo_context tool
```

### 3.2 Detailed Component Specs

#### 3.2.1 Chunker (`indexing/chunker.py`)

Breaks source files into searchable text chunks.

- **Language detection**: file extension → language (Python, JS/TS, Rust, Go, Java, C/C++, Ruby, docs)
- **Boundary detection**: regex patterns per language for `def`, `class`, `function`, `fn`, etc.
- **Python**: indentation-aware region detection
- **Brace-based languages**: `{` / `}` depth counting
- **Document files**: split by Markdown `#` headings
- **Max chunk size**: 8,000 characters; falls back to fixed-size line chunks
- **Token estimate**: `len(text) // 4`

```
chunk_file(file_path, content)
  ├─ _detect_language(file_path)
  ├─ if doc → _chunk_doc(content)
  ├─ if len(content) <= 8000 → single Chunk
  ├─ _find_boundaries(lines, language)
  │   └─ per-language regex → [(start, end, kind, name), ...]
  ├─ _chunk_by_boundaries(lines, boundaries, language)
  │   └─ if chunk > 8000 chars → recurse _chunk_fixed()
  └─ fallback: _chunk_fixed(lines)
```

Output: `list[Chunk]` with `start_line`, `end_line`, `chunk_type`, `symbol_name`, `content`, `estimated_tokens`, `content_hash`.

#### 3.2.2 File Discovery (`indexing/discovery.py`)

Walks a repository directory and returns files eligible for indexing.

- Loads `.gitignore` from the repo root
- Applies a built-in exclusion list (`.pyc`, `node_modules/`, `.ssh/`, secrets, etc.)
- Skips: symlinks, binary files (null-byte heuristic + extension list), empty files, files > 1 MB
- Computes SHA-256 content hash for each file
- Returns sorted `list[DiscoveredFile]`

```
discover_files(repo_root)
  └─ os.walk(repo_root, followlinks=False)
      ├─ prune dirs by gitignore + exclude + hidden
      ├─ per file:
      │   ├─ gitignore match → skip
      │   ├─ exclude match → skip
      │   ├─ symlink → skip
      │   ├─ path traversal → skip
      │   ├─ secret file → skip
      │   ├─ > 1MB → skip
      │   ├─ empty → skip
      │   ├─ binary → skip
      │   └─ sha256 hash → DiscoveredFile
      └─ sort by relative_path
```

#### 3.2.3 Indexer (`indexing/indexer.py`)

Orchestrates the indexing pipeline:

**`scan_repository(session, repo_id, job_id)`** — full scan:

1. Create `IndexGeneration` (state=`building`)
2. `discover_files(repo.git_path)` → file list
3. For each file:
   - Compare SHA-256 hash with stored `FileRecord`; skip unchanged
   - Read content, call `chunk_file()`, redact secrets
   - Upsert `FileRecord`, create `Chunk` objects (embedding=`None`)
   - Extract `Symbol` entries from function/class chunks
4. Flush chunks to DB
5. Batch-generate embeddings via Ollama (`get_embeddings_batch`)
6. Mark old-generation chunks as `stale=True`
7. Mark deleted files (present in DB but absent on disk)
8. Set generation state to `active`, complete job

**`incremental_scan(session, repo_id)`** — change detection:

1. Check for active generation; if absent → enqueue initial scan
2. Compare discovered files' hashes against stored `FileRecord` hashes
3. If **any** hash differs, file is new, or file was deleted → enqueue scan

**`worker_tick(session)`** — background polling:

```
every 10 seconds:
  ├─ SELECT index_jobs WHERE status='pending' ORDER BY created_at LIMIT 5
  ├─ for each job:
  │   ├─ UPDATE status='running'
  │   ├─ if job_type == 'initial_scan':
  │   │   └─ scan_repository(session, repo_id, job_id)
  │   ├─ on success: UPDATE status='completed'
  │   └─ on exception: ROLLBACK → UPDATE status='failed'
  └─ COMMIT
```

#### 3.2.4 Hybrid Search (`retrieval/search.py`)

The search pipeline runs 4 sub-queries and fuses results with RRF:

```
hybrid_search(session, request)
  │
  ├─ 1. Generate query embedding (Ollama)
  │
  ├─ 2a. EXACT sub-search
  │   └─ WHERE content ILIKE '%query%' AND NOT stale
  │       → up to 100 candidates, scores = 1.0
  │
  ├─ 2b. LEXICAL (FTS) sub-search
  │   └─ WHERE to_tsvector('english', content) @@ plainto_tsquery(...)
  │       AND NOT stale ORDER BY ts_rank DESC
  │       → up to 100 candidates, rank-normalized scores
  │
  ├─ 2c. SEMANTIC (vector) sub-search
  │   └─ ORDER BY embedding <=> query_embedding
  │       AND NOT stale LIMIT 100
  │       → cosine distance → 1.0 - distance scores
  │
  ├─ 2d. SYMBOL sub-search
  │   └─ JOIN chunks ON chunks.symbol_name ILIKE '%query%'
  │       → up to 100 candidates
  │
  ├─ 3. Reciprocal Rank Fusion
  │   └─ for each candidate across all methods:
  │       score = SUM(1 / (k + rank_in_method))
  │       k = 60 (standard RRF constant)
  │
  ├─ 4. Staleness check
  │   └─ if generation is > 1 hour old → is_stale = True
  │
  ├─ 5. Token budget filtering
  │   └─ accumulate estimated_tokens; stop if budget exceeded
  │
  └─ 6. Sort by final score DESC, return top N results
```

#### 3.2.5 Embedding Adapter (`indexing/embeddings/adapter.py`)

Client for the Ollama embedding API:

- Calls `{OLLAMA_BASE_URL}/api/embeddings` with the configured model
- Batches requests (`embedding_batch_size = 16` from config)
- Returns 768-dimensional float vectors
- Handles timeouts, retries, and connection errors

#### 3.2.6 MCP Tools (`mcp/fastmcp.py`)

14 tools registered with FastMCP. Every tool is wrapped with `_instrument_tool()` which records Prometheus metrics (calls/success/error, latency histogram). Search-class tools get an additional `_instrument_search()` wrapper for query-specific metrics.

Tool inventory:

| # | Tool | Category | Instrumentation |
|---|------|----------|----------------|
| 1 | `repo_list` | Repository | `_instrument_tool` |
| 2 | `repo_search` | Search | `_instrument_tool` + `_instrument_search` |
| 3 | `repo_symbol` | Search | `_instrument_tool` |
| 4 | `repo_context` | Search | `_instrument_tool` + `_instrument_search` |
| 5 | `index_status` | Status | `_instrument_tool` |
| 6 | `memory_write` | Memory | `_instrument_tool` |
| 7 | `memory_record` | Memory (alias) | `_instrument_tool` |
| 8 | `memory_search` | Memory | `_instrument_tool` |
| 9 | `checkpoint_save` | Checkpoint | `_instrument_tool` |
| 10 | `checkpoint_get` | Checkpoint | `_instrument_tool` |
| 11 | `task_resume` | Checkpoint (alias) | `_instrument_tool` |
| 12 | `compaction_checkpoint_save` | Checkpoint | `_instrument_tool` |
| 13 | `session_bootstrap` | Checkpoint | `_instrument_tool` |
| 14 | `repo_dependencies` | Graph | `_instrument_tool` |

#### 3.2.7 Security Layer

```
Content → redact_content(chunk.text)
  ├─ regex patterns for: passwords, API keys, tokens, private keys, AWS creds
  ├─ matched patterns → placeholders
  └─ returns (cleaned_text, patterns_matched, pattern_labels)

Logs → apply_credential_filter()
  └─ filters log lines to redact passwords, connection strings

Paths → is_safe_relative_path(), is_secret_file()
  └─ prevents path traversal, blocks known secret file patterns
```

---

## 4. Request Flow Diagrams

### 4.1 Indexing Flow (Auto-discovery → Indexed)

```
User mounts repo in compose.yaml
         │
         ▼
repo-intel repo add --name "FLOW" /repos/FLOW
         │
         ▼
  INSERT INTO repositories (name, git_path, status='registered')
         │
         ▼
Worker tick (every 10s)
         │
         ▼
incremental_scan(session, repo_id)
         │
         ├─ No active generation?
         │   └─ YES → enqueue IndexJob(status='pending', job_type='initial_scan')
         │
         ├─ Active generation exists?
         │   └─ Compare discovered files vs FileRecord hashes
         │       ├─ Any hash different / new file / deleted file?
         │       │   └─ YES → enqueue IndexJob
         │       └─ All identical? → skip (nothing to do)
         │
         ▼
Worker tick picks up pending IndexJob
         │
         ├─ scan_repository(session, repo_id, job_id)
         │   │
         │   ├─ CREATE IndexGeneration(state='building')
         │   ├─ discover_files('/repos/FLOW')
         │   │   └─ skip .gitignore, binaries, secrets, >1MB
         │   │
         │   ├─ for each file:
         │   │   ├─ hash matches existing? → skip
         │   │   ├─ read content
         │   │   ├─ chunk_file(path, content)
         │   │   │   └─ language-aware boundary detection
         │   │   ├─ redact_content(chunk.content)
         │   │   ├─ INSERT FileRecord (if new)
         │   │   ├─ INSERT Chunk(embedding=NULL)
         │   │   └─ INSERT Symbol (if function/class chunk)
         │   │
         │   ├─ FLUSH chunks to DB
         │   ├─ get_embeddings_batch(all pending chunks, via Ollama)
         │   │   └─ batches of 16
         │   ├─ UPDATE Chunk SET embedding = <vector>
         │   ├─ UPDATE Chunk SET stale=True WHERE generation != current
         │   ├─ UPDATE FileRecord SET deleted=True (removed files)
         │   ├─ UPDATE IndexGeneration SET state='active'
         │   └─ UPDATE IndexJob SET status='completed'
         │
         └─ COMMIT
```

### 4.2 Search Flow (Agent Query → Results)

```
Agent (via MCP or REST)
         │
         ├─ POST /api/search/ {"query": "authentication", "limit": 10}
         │  OR tools.repo_intel["repo_search"](query="...")
         │
         ▼
FastAPI / FastMCP
         │
         ▼
  SEARCH_REQUESTS.inc()
         │
         ▼
hybrid_search(session, SearchRequest)
         │
         ├─ Step 1: embedding = await get_embedding(query)
         │   └─ POST {OLLAMA_BASE_URL}/api/embeddings
         │
         ├─ Step 2: Run 4 sub-searches
         │   │
         │   ├─ [EXACT]  content ILIKE '%auth%' AND NOT stale
         │   ├─ [FTS]    to_tsvector @@ plainto_tsquery AND NOT stale
         │   ├─ [VECTOR] embedding <=> query_embedding AND NOT stale
         │   └─ [SYMBOL] symbol_name ILIKE '%auth%'
         │
         ├─ Step 3: RRF Fusion → rrf_score per unique chunk_id
         ├─ Step 4: Sort by rrf_score DESC
         ├─ Step 5: annotation (generation > 1h → is_stale)
         ├─ Step 6: Token budget clamp
         │
         ▼
Return results + INSERT RetrievalEvent (query, timing, chunk_ids, stale_count)
         │
         └─ emit SEARCH_LATENCY, SEARCH_RESULTS, SEARCH_STALE_RESULTS metrics
```

### 4.3 MCP Tool Call Flow (Agent → Response)

```
OpenCode Agent (Code Mode)
         │
         ├─ tools.repo_intel["repo_search"](query="how to auth", limit=5)
         │
         ▼
MCP Transport (SSE on /mcp)
         │
         └─ JSON-RPC 2.0 call → FastMCP
         │
         ▼
_instrument_tool("repo_search") decorator
         │
         ├─ MCP_TOOL_LATENCY.start()
         ├─ _instrument_search decorator
         │   └─ SEARCH_REQUESTS.inc()
         │
         ├─ await repo_search(query, repository_id, limit)
         │   │
         │   ├─ open async DB session
         │   ├─ hybrid_search(session, SearchRequest)
         │   │   └─ (see search flow §4.2)
         │   └─ serialize results → dict
         │
         ├─ on success: MCP_TOOL_CALLS{status=success}.inc()
         └─ on error:  MCP_TOOL_CALLS{status=error}.inc()
         │
         ▼
MCP response → Agent receives dict with results, scores, staleness flags
```

### 4.4 Memory Read/Write Flow

```
Agent calls tools.repo_intel["memory_write"](kind, statement)
         │
         ▼
FastMCP → memory_write()
         │
         ├─ validate repository_id (if given)
         ├─ INSERT Memory(
         │     kind, statement, status='candidate',
         │     evidence, source_commit, author
         │   )
         └─ COMMIT → return {id, kind, statement, status, message}

Agent calls tools.repo_intel["memory_search"](query, kind, limit)
         │
         ▼
FastMCP → memory_search()
         │
         ├─ SELECT Memory WHERE kind=... AND statement ILIKE %query%
         ├─ ORDER BY id DESC LIMIT limit
         └─ return {num_memories, memories: [...]}

Agent calls memory_record(...)  (alias)
         │
         └─ delegates to memory_write() internally
```

### 4.5 Checkpoint and Bootstrap Flow

```
━━━ Before Compaction ━━━

Agent calls compaction_checkpoint_save(objective, session_id, ...)
         │
         ├─ INSERT TaskCheckpoint(
         │     objective, current_state, changed_files,
         │     pending_steps, evidence.compaction.save_type=pre_compaction
         │   )
         └─ COMMIT → return {id, session_id, objective, created_at}

━━━ Auto Checkpoint (Safeguard) ━━━

AutoCheckpointScheduler (runs every 15 min in API lifespan)
         │
         ├─ SELECT TaskCheckpoint WHERE created_at < now - 4h
         ├─ for each: evidence.compaction.marked_stale_at = now
         └─ COMMIT

━━━ After Compaction / Restart ━━━

Agent calls session_bootstrap(session_id, repository_id)
         │
         ├─ SELECT latest TaskCheckpoint (filtered by session_id, repo_id)
         └─ SELECT recent verified Memory rows
         │
         └─ return {
               checkpoint: {objective, current_state, pending_steps, ...},
               verified_memories: [...],
               restored: true
             }

Agent calls checkpoint_get(session_id)  (or task_resume alias)
         │
         └─ SELECT latest TaskCheckpoint → return {id, state, files, steps}
```

---

## 5. Data Model

### 5.1 Entity-Relationship Overview

```
repositories (1) ──── (N) file_records (1) ──── (N) chunks
      │                     │                          │
      │                     │                          │
      ├─── (1) ──── (N) symbols (N) ──── (1) symbol_edges
      │
      ├─── (1) ──── (N) index_generations (1) ──── (N) chunks
      │
      ├─── (1) ──── (N) index_jobs
      │
      ├─── (1) ──── (N) memories
      │
      └─── (1) ──── (N) task_checkpoints
```

### 5.2 Table Definitions

#### `repositories`

| Column | Type | Constraint | Description |
|--------|------|-----------|-------------|
| `id` | UUID | PK | Repository identifier |
| `name` | varchar(255) | NOT NULL | Human-readable name |
| `git_path` | varchar(1024) | UNIQUE, NOT NULL | Absolute path inside container |
| `status` | varchar(32) | default `registered` | `registered`, `indexed`, `error` |
| `include_patterns` | JSONB | nullable | Glob patterns to include |
| `exclude_patterns` | JSONB | nullable | Glob patterns to exclude |

#### `files` (FileRecord)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | File identifier |
| `repository_id` | UUID FK → repositories | Parent repository |
| `relative_path` | varchar(2048) | Path relative to repo root |
| `language` | varchar(64) | Detected language |
| `size_bytes` | int | File size |
| `content_hash` | varchar(64) | SHA-256 hex digest |
| `git_head` | varchar(40) | Git commit at index time |
| `worktree_dirty` | bool | Uncommitted changes |
| `deleted` | bool | Soft-delete flag |

Unique constraint: `(repository_id, relative_path)`.

#### `index_generations`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Generation identifier |
| `repository_id` | UUID FK → repositories | Parent repository |
| `state` | varchar(32) | `building` → `active` / `failed` / `retired` |
| `embedding_model` | varchar(255) | Model used (e.g., `nomic-embed-text`) |
| `embedding_dimension` | int | Vector dimension (768) |
| `chunker_version` | varchar(64) | Chunker version string |
| `chunk_count` | int | Number of chunks in this generation |

Each index scan creates a new generation. The one with `state='active'` serves search queries.

#### `chunks`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Chunk identifier |
| `file_id` | UUID FK → files | Parent file |
| `generation_id` | UUID FK → index_generations | Index generation |
| `start_line`, `end_line` | int | Line range (1-based) |
| `chunk_type` | varchar(32) | `function`, `class`, `file`, `doc` |
| `symbol_name` | varchar(512) | Symbol this chunk belongs to |
| `content_hash` | varchar(64) | SHA-256 of chunk content |
| `content` | text | Chunk text (redacted) |
| `estimated_tokens` | int | Rough token count (`len/4`) |
| `embedding` | Vector(768) | pgvector embedding |
| `stale` | bool | `True` if generation is no longer active |

Unique constraint: `(generation_id, content_hash)`.

#### `symbols`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Symbol identifier |
| `file_id` | UUID FK → files | Parent file |
| `name` | varchar(512) | Symbol name |
| `fully_qualified` | varchar(1024) | Fully qualified name |
| `kind` | varchar(32) | `function`, `class`, `method`, etc. |
| `start_line`, `end_line` | int | Line range |
| `parser_source` | varchar(64) | Parser used (`text`) |
| `generation_id` | UUID FK → index_generations | Index generation |

#### `symbol_edges`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Edge identifier |
| `repository_id` | UUID FK → repositories | Repository |
| `from_symbol_id` | UUID FK → symbols | Source symbol |
| `to_symbol_id` | UUID FK → symbols | Target symbol |
| `relation_type` | varchar(32) | `imports`, `calls`, `references` |
| `evidence_location` | varchar(512) | Where edge was found |
| `confidence` | float | Edge confidence score |
| `generation_id` | UUID FK → index_generations | Index generation |

#### `index_jobs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Job identifier |
| `repository_id` | UUID FK → repositories | Target repository |
| `job_type` | varchar(32) | `initial_scan`, `incremental`, `refresh` |
| `status` | varchar(32) | `pending` → `running` → `completed`/`failed` |
| `attempts` | int | Retry count |
| `max_attempts` | int | Max retries (default 3) |
| `error_summary` | text | Error message if failed |
| `dedupe_key` | varchar(256) | Deduplication key |

#### `memories`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Memory identifier |
| `repository_id` | UUID FK, nullable | Scoping repository (or global) |
| `kind` | varchar(64) | `preference`, `observation`, `instruction` |
| `statement` | text | Memory content |
| `status` | varchar(32) | `candidate` → `verified` / `superseded` / `rejected` |
| `evidence` | JSONB | Supporting evidence |
| `source_commit` | varchar(40) | Git commit hash |
| `author` | varchar(128) | Agent session or user |
| `expiry_time` | timestamptz | When to re-evaluate |

#### `task_checkpoints`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Checkpoint identifier |
| `repository_id` | UUID FK, nullable | Related repository |
| `session_id` | varchar(256) | Agent session identifier |
| `objective` | text | Task objective |
| `current_state` | text | Work done so far |
| `changed_files` | JSONB | Modified file paths |
| `pending_steps` | JSONB | Remaining work items |
| `evidence` | JSONB | Data + compaction metadata |
| `created_at` | timestamptz | Checkpoint timestamp |

#### `retrieval_events`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID PK | Event identifier |
| `repository_id` | UUID FK, nullable | Repository scope |
| `request_id` | varchar(64) | Request trace ID |
| `query` | text | Search query |
| `num_results` | int | Results returned |
| `token_budget` | int | Token budget |
| `estimated_tokens_returned` | int | Actual tokens |
| `elapsed_ms` | int | Query latency |
| `generation_id` | UUID | Index that served the query |
| `selected_chunk_ids` | JSONB | Chunk IDs returned |
| `stale_count` | int | Stale chunks in results |

---

## 6. Memory System

### 6.1 Purpose

The memory subsystem provides persistent, evidence-backed state for coding agents. An agent records observations, preferences, and instructions during a session, and retrieves them later across restarts or after context compaction.

### 6.2 Memory Lifecycle

```
Write → status = 'candidate'
         │
         ├─ Agent or operator promotes:
         │   └─ status = 'verified'
         │
         ├─ New evidence contradicts:
         │   └─ status = 'superseded'
         │
         ├─ Evidence disproved:
         │   └─ status = 'rejected'
         │
         └─ expiry_time reached → re-evaluate
```

### 6.3 Scoping

- **Global**: `repository_id = NULL` — applies across all repos
- **Repo-scoped**: `repository_id = <uuid>` — applies only to that repo

### 6.4 How It Works

**Write** (`memory_write` / `memory_record`):

```python
tools.repo_intel["memory_write"](
    kind="preference",
    statement="Use typing.Optional instead of Optional for new code",
    repository_id="<uuid>",
    evidence={"reason": "PEP 604 style guide adopted"},
)
```

**Read** (`memory_search`):

- Filters by `repository_id`, `kind`
- Full-text search on `statement` (ILIKE)
- Returns memories ordered by recency

**Bootstrap** (`session_bootstrap`):

```
session_bootstrap(session_id, repository_id)
  ├─ fetch latest TaskCheckpoint for this session
  ├─ fetch all verified memories (status='verified')
  │   └─ scoped to repository_id if given
  └─ return combined context for agent reconstruction
```

### 6.5 Storage and Search

Memories are stored as plain rows in the `memories` table. Search uses:
- Exact filtering on `kind`, `status`, `repository_id`
- ILIKE text search on `statement` for free-text queries
- Relevance scoring with word-match and verified-status boosting

---

## 7. Checkpoint and Session Persistence

### 7.1 Why Checkpoints Exist

OpenCode's context window is finite. When it fills up, the system performs **compaction** (summarizing conversation history). Without external state, the agent loses track of:
- What it was working on
- Which files it modified
- What steps remain
- What decisions were made

Checkpoints solve this by persisting state to the database.

### 7.2 Checkpoint Types

| Type | When | Tool | Special Handling |
|------|------|------|------------------|
| **Regular** | On demand | `checkpoint_save` | Stores objective, state, files, steps |
| **Compaction** | Before compaction | `compaction_checkpoint_save` | Same + `evidence.compaction.save_type = "pre_compaction"` |
| **Auto** | Every 15 min (background) | — | Marks old checkpoints stale if > 4h |

### 7.3 Resume Flow

```
Agent starts (or resumes after compaction)
         │
         ▼
session_bootstrap(session_id, repository_id)
         │
         ├─ 1. Load latest checkpoint:
         │     ├─ objective
         │     ├─ current_state  ("Implemented auth in module X")
         │     ├─ changed_files  (["auth.py", "config.py"])
         │     └─ pending_steps  (["Test error cases", "Add docs"])
         │
         ├─ 2. Load verified memories
         │
         └─ 3. Agent reconstructs working context from returned data
```

### 7.4 Staleness Management

The `AutoCheckpointScheduler` runs in the API container's lifespan:

```
every 15 minutes:
  SELECT TaskCheckpoint WHERE created_at < now - 4 hours
  for each:
    if not already marked:
      SET evidence.compaction.marked_stale_at = now
```

This prevents agents from resuming from stale state when repos have moved on.

---

## 8. Configuration

### 8.1 Settings (`.env`)

All settings are loaded via `pydantic-settings` from `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROFILE` | `remote-ollama` | Profile: `local` or `remote-ollama` |
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8765` | Bind port |
| `DATABASE_URL` | `postgresql+psycopg://...` | async DB URL |
| `REPO_ROOTS` | `/workspace` | Comma-separated repo mount paths |
| `OLLAMA_BASE_URL` | `http://192.168.68.62:11434` | Ollama HTTP endpoint |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for embeddings |
| `EMBEDDING_BATCH_SIZE` | `16` | Embedding batch size |
| `OLLAMA_TIMEOUT_SECONDS` | `30` | Embedding request timeout |
| `INDEX_POLL_SECONDS` | `10` | Worker poll interval |
| `MAX_FILE_BYTES` | `1048576` | Skip files larger than 1 MB |
| `DEFAULT_CONTEXT_TOKENS` | `12000` | Default token budget for context packs |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FORMAT` | `text` | `text` or `json` |

### 8.2 Auto-Checkpoint Tuning

| Threshold | Default | Code Location |
|-----------|---------|---------------|
| Auto-checkpoint interval | 900 s (15 min) | `manager.DEFAULT_AUTO_CHECKPOINT_INTERVAL_S` |
| Stale checkpoint threshold | 4 hours | `manager.DEFAULT_CHECKPOINT_STALE_THRESHOLD_H` |

### 8.3 Docker Compose Volumes

```yaml
volumes:
  pgdata:        # PostgreSQL persistent data
  promdata:      # Prometheus persistent data
  grafanadata:   # Grafana persistent data
  # Add repo mounts under services.api.volumes and services.worker.volumes:
  # - /host/path/to/repo:/repos/repo-name:ro
```

---

## 9. Error Handling and Resilience

### 9.1 Index Job Failures

```
scan_repository() raises exception
  │
  ├─ session.rollback()   (clean stale ORM state)
  ├─ UPDATE index_jobs SET status='failed', error_summary=..., attempts+=1
  └─ If attempts >= max_attempts (3): job considered dead
      └─ Agent must manually re-trigger via: repo-intel index --repo-path /repos/FLOW
```

### 9.2 Embedding Failures

If Ollama is down during indexing:
- `Chunk` rows are created with `embedding = NULL`
- Search vector sub-query returns no candidates for those chunks
- Exact + FTS sub-queries still work
- Restart Ollama and re-index to fix

### 9.3 Database Pool

- Pool size: 5, max overflow: 10
- `pool_pre_ping=True`: connections tested before use
- Connection health exposed via `/health/ready` endpoint

---

## 10. Security

### 10.1 Secret Redaction Pipeline

```
Source file content
  → chunk_file() produces text chunks
    → redact_content(text) scans for patterns
      ├─ password=..., api_key=..., secret=...
      ├─ AWS keys, private keys, tokens
      └─ replaces matches with [REDACTED]
    → cleaned_text stored in chunks.content
```

### 10.2 Path Safety

- `is_safe_relative_path()`: validates against `..` traversal
- `is_secret_file()`: blocks `.ssh/`, `id_rsa`, `netrc`, `terraform.tfvars`, etc.
- Symlinks are skipped during discovery

### 10.3 Log Filtering

`apply_credential_filter()` wraps the root logger to strip passwords and secrets from log output.

---

## 11. Observability

### 11.1 Prometheus Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `search_requests_total` | Counter | `source` | Count of searches (rest/mcp) |
| `search_latency_seconds` | Histogram | — | End-to-end search latency |
| `search_results_count` | Gauge | — | Results returned per query |
| `search_stale_results_total` | Counter | — | Stale chunks served |
| `mcp_tool_calls_total` | Counter | `tool_name`, `status` | MCP call success/error |
| `mcp_tool_latency_seconds` | Histogram | `tool_name` | MCP call latency |
| `http_request_duration_seconds` | Histogram | `method`, `status` | HTTP request latency |
| `db_pool_connections` | Gauge | `state` | Connection pool state |

### 11.2 RetrievalEvent Audit Trail

Every search through the REST API writes a `RetrievalEvent` row:
- Query text, result count, latency
- Which generation served it
- Which chunks were selected
- How many were stale

This enables offline analysis of search quality over time.
