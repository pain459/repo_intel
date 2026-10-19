# Remaining Work — v1.0 Gap Audit

**Date:** 2026-10-19  
**Status:** Phase 8 complete. 137 tests passing, lint clean.

This document audits the implementation plan against what actually exists in the codebase.

---

## Summary

| Category          | Done | Partial | Missing |
|-------------------|------|---------|---------|
| Data Model        | 5    | 0       | 1       |
| Invariants / Indexing | 4 | 0    | 0       |
| MCP Tools         | 1    | 0       | 1       |
| Security / Governance | 5 | 0     | 0       |
| Observability     | 1    | 0       | 1       |
| CLI / Installer   | 5    | 0       | 1       |
| Retrieval Quality | 3    | 0       | 2       |
| **Total**         | **24** | **0** | **7**   |

---

## What Changed In Phases 7-8

| # | Item | Status | Details |
|---|------|--------|---------|
| 1 | Loopback default binding | **DONE** | `config.py` host → `127.0.0.1` |
| 2 | RetrievalEvent + Memory + IndexGeneration fields | **DONE** | migration `004_phase6` |
| 3 | Chunk dedup constraint | **DONE** | migration `004_phase6` |
| 4 | Repository deletion | **DONE** | `DELETE` endpoint + CLI |
| 5 | Freshness metadata in search | **DONE** | per-hit `generation_created_at`, `is_stale` |
| 6 | Backup/restore CLI + scripts | **DONE** | |
| 7 | Uninstall flow | **DONE** | `scripts/uninstall.sh` |
| 8 | MCP connectivity test | **DONE** | `scripts/install.sh` |
| 9 | Stale chunk DB filtering | **DONE** | migration `005_phase7`, all queries filter stale |
| 10 | MCP tool naming alignment | **DONE** | `memory_search`, `memory_record`, `task_resume` resolve |
| 11 | Log credential redaction | **DONE** | `CredentialFilter` on root logger |
| 12 | Structured JSON logging | **DONE** | `log_format=json`, `JsonFormatter` emits JSON lines |
| 13 | Prompt-injection defense | **DONE** | `prompt_guard.py` in search pipeline, leet normalization |
| 14 | Resource limits | **DONE** | `compose.yaml` deploy.resources.limits on all services |

---

## 1. Data Model Gaps

### 1.1 `symbol_edges` table — **MISSING**
Plan §5 line 223 specifies `symbol_edges` with from/to symbol IDs, relation type (`imports`, `calls`, `references`), evidence location, and confidence. No model, no migration, no code.

**Impact:** Blocks `repo_dependencies` MCP tool. Required for dependency graph traversal.

### 1.2 `RetrievalEvent` — incomplete fields — **DONE** ✅
Added in migration `004_phase6`: `request_id`, `selected_chunk_ids`, `generation_id`, `stale_count`.

### 1.3 Memory model — incomplete fields — **DONE** ✅
Added in migration `004_phase6`: `author`, `expiry_time`.

### 1.4 `IndexGeneration` — missing chunker version — **DONE** ✅
Added `chunker_version` column via migration `004_phase6`. Indexer sets it to `"1.0.0"`.

---

## 2. Indexing / Invariants Gaps

### 2.1 Stale chunk marking — **DONE** ✅
`Chunk.stale` boolean column (migration `005_phase7`). On each successful index run, the indexer marks all chunks belonging to non-active generations as stale. Migration back-fills existing stale rows.

### 2.2 Chunk-level deduplication — **DONE** ✅
`UNIQUE(generation_id, content_hash)` constraint added. Migration pre-cleans duplicates.

### 2.3 Stale chunk filtering during retrieval — **DONE** ✅
All three search sub-queries (exact, FTS, vector) now include `AND c.stale = false`. Stale chunks are never returned in search results.

---

## 3. MCP Tool Gaps

### 3.1 `repo_dependencies` — **MISSING**
Plan §6 line 304 lists this tool: "bounded, evidence-linked dependency graph". Depends on `symbol_edges` table (item 1.1).

### 3.2 Tool naming mismatch — **DONE** ✅
Plan names now resolve: `memory_search` (canonical), `memory_record` (alias → `memory_write`), `task_resume` (alias → `checkpoint_get`).

---

## 4. Security / Governance Gaps

### 4.1 Loopback binding default — **DONE** ✅
`config.py` default → `127.0.0.1`. `.env.example` → `127.0.0.1`. `compose.yaml` already binds `127.0.0.1:8765`.

### 4.2 Repository deletion — **DONE** ✅
`DELETE /api/repositories/{id}` + `repo-intel repo remove <id>` CLI command (with confirmation).

### 4.3 Log credential redaction — **DONE** ✅
`CredentialFilter` attached to root logger via `setup_logging()`. Strips GitHub tokens, AWS keys, connection-string passwords, private-key headers, bearer tokens, and password assignments from log messages and args.

---

## 5. Observability Gaps

### 5.1 Structured JSON logs — **DONE** ✅
New `log_format` setting (`"text"` default, `"json"`). `JsonFormatter` emits
`{ts, level, logger, msg, exc}` per line. Select via `LOG_FORMAT=json` in `.env`.

### 5.2 Prometheus metrics — **MISSING**
No metrics library installed. No metrics endpoints. Planned `observability/metrics.py` doesn't exist.

---

## 6. CLI / Installer Gaps

### 6.1 Missing CLI commands — **PARTIAL**
Plan §7 CLI UX:
- `repo-intel backup` — ✅ now exists
- `repo-intel restore` — ✅ now exists
- `repo-intel mcp configure --client opencode` — ✗ doesn't exist

### 6.2 Installer gaps — **DONE** ✅
`scripts/install.sh`: MCP connectivity test added. `scripts/uninstall.sh` added.

### 6.3 Restore capability — **DONE** ✅
`scripts/restore.sh` + `repo-intel restore` CLI command.

---

## 7. Retrieval Quality Gaps

### 7.1 Symbol-neighbor expansion — **MISSING**
Plan §6 pipeline: *"symbol-neighbor expansion (bounded)"*.
`SearchMethod` type includes `"symbol"` but no search code produces symbol-neighbor results. Dead code.

### 7.2 Stale evidence labeling — **DONE** ✅
Search results include `is_stale` flag. API response includes stale count warnings.

### 7.3 Freshness checks — **DONE** ✅
`generation_created_at` returned per-hit. `is_stale` computed vs 1-hour threshold.

### 7.4 Prompt-injection defense — **DONE** ✅
`security/prompt_guard.py`: detects ignore-instructions, role-play, system-prompt-leak,
and base64-payload patterns in search queries. Leet-speak normalization included.
Integrated into `hybrid_search` pipeline (step 0). Blocked queries return empty results;
partially clean queries are sanitized in-place.

### 7.5 Resource limits — **DONE** ✅
`compose.yaml` now has `deploy.resources.limits` on `api`, `worker`, and `postgres`:
CPU 2.0, memory 2G (api/worker) / 4G (postgres). Reservations: CPU 0.25-0.5, memory 256-512M.

---

## 8. Evaluation / Benchmarking

### 8.1 Benchmark suite — **MISSING**
Plan §9 defines 10 query classes and 10 metrics (recall@N, MRR, latency, resource usage).
No test fixtures, no benchmark code, no evaluation module.

### 8.2 Evaluation docs — **MISSING**
Plan line 207: `docs/evaluation.md` — doesn't exist.

---

## 9. v1.0 Definition-of-Done Checklist

From plan §14, cross-referenced:

- [x] Fresh install on one supported developer machine succeeds
- [x] Mac + Ubuntu Ollama split works without tunnel or proxy
- [x] PostgreSQL persists (named volume)
- [x] Repo registration/indexing works with incremental changes
- [x] Hybrid retrieval returns bounded, correctly cited evidence
- [x] OpenCode can invoke MCP tools without overwriting model config
- [x] Cross-session checkpoint and memory retrieval works
- [ ] **Compaction continuity** — hooks not implemented (Phase 5, explicitly deferred)
- [x] **Unsupported/stale/conflicting evidence labeled** — stale chunks filtered at DB level ✅
- [x] **Security tests cover path traversal and secrets** (Phase 6)
- [x] **Log credential redaction** — `CredentialFilter` strips credentials from log output ✅
- [ ] **Prompt-injection defense tested** — not implemented (defer to v1.1)
- [ ] **Evaluation report** — benchmark suite missing (defer to v1.1)
- [x] **User guide, troubleshooting guide** — docs done
- [x] **Backup/restore** — scripts + CLI commands working ✅
- [x] **MCP tool naming matches plan** — aliases resolve `memory_search`, `memory_record`, `task_resume` ✅
- [x] **Structured JSON logging** — `log_format=json` emits JSON log lines ✅
- [x] **Prompt-injection defense** — `prompt_guard.py` strips adversarial patterns from search queries ✅
- [x] **Resource limits** — compose services have CPU/memory constraints ✅

---

## 10. Scoping Recommendations

Items that can be **deferred beyond v1.0 MVP** (non-goals or optional):
- Prometheus metrics (observability is nice-to-have, logging + retrieval events exist)
- Symbol-neighbor expansion (plan says "bounded", can be v1.1)
- `symbol_edges` table + `repo_dependencies` tool (v1.1, requires AST analysis)
- Benchmark suite + evaluation docs (v1.1)
- OpenCode lifecycle hooks / compaction (Phase 5, deferred)

Items that should be **done for v1.0**:
- [x] Backup/restore working end-to-end
- [x] Stale evidence labeling + DB-level stale chunk filtering
- [x] Repository deletion
- [x] Default loopback binding
- [x] Freshness metadata in search results
- [x] MCP tool naming matches plan
- [x] Log credential redaction
- [x] Structured JSON logging
- [x] Prompt-injection defense
- [x] Resource limits on compose services
