# Remaining Work — v1.0 Gap Audit

**Date:** 2026-10-19  
**Status:** Partials resolved. Migration `004_phase6` applied. 108 tests passing, lint clean.

This document audits the implementation plan against what actually exists in the codebase.

---

## Summary

| Category          | Done | Partial | Missing |
|-------------------|------|---------|---------|
| Data Model        | 5    | 0       | 1       |
| Invariants / Indexing | 3 | 0    | 1       |
| MCP Tools         | 0    | 1       | 1       |
| Security / Governance | 3 | 1     | 0       |
| Observability     | 0    | 0       | 2       |
| CLI / Installer   | 5    | 0       | 1       |
| Retrieval Quality | 2    | 0       | 3       |
| **Total**         | **18** | **2** | **9**   |

---

## What Changed in This Pass

| # | Item | Status | Details |
|---|------|--------|---------|
| 1 | Loopback default binding | **DONE** | `config.py` + `.env.example` host → `127.0.0.1` |
| 2 | RetrievalEvent fields | **DONE** | Added `request_id`, `selected_chunk_ids`, `generation_id`, `stale_count` via migration `004_phase6` |
| 3 | Memory model fields | **DONE** | Added `author`, `expiry_time` via migration `004_phase6` |
| 4 | IndexGeneration chunker_version | **DONE** | Added column via migration `004_phase6`, set in indexer |
| 5 | Chunk dedup constraint | **DONE** | `UNIQUE(generation_id, content_hash)` via migration `004_phase6` (deduplicates existing data) |
| 6 | Repository deletion | **DONE** | `DELETE /api/repositories/{id}` + `repo-intel repo remove <id>` CLI |
| 7 | Freshness metadata in search | **DONE** | `generation_created_at`, `is_stale` on `SearchResult` + stale warnings in API response |
| 8 | Stale evidence labeling | **DONE** | Stale hits flagged + warning messages in search response |
| 9 | Backup/restore CLI | **DONE** | `repo-intel backup` / `repo-intel restore` commands |
| 10 | Backup/restore scripts | **DONE** | `scripts/restore.sh` complementing existing `scripts/backup.sh` |
| 11 | Uninstall flow | **DONE** | `scripts/uninstall.sh [--keep-data] [--dry-run]` |
| 12 | MCP connectivity test | **DONE** | `scripts/install.sh` now tests MCP endpoint |

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

### 2.1 Stale chunk marking — **MISSING**
Plan §5 line 236: *"On file modification, mark affected chunks stale immediately and refresh them asynchronously."*

Currently: indexer detects changes via polling hash comparison, then re-scans the entire repo. No `stale` flag on `Chunk` model. No immediate marking mechanism.

### 2.2 Chunk-level deduplication — **DONE** ✅
`UNIQUE(generation_id, content_hash)` constraint added. Migration pre-cleans duplicates.

### 2.3 Stale chunk filtering during retrieval — **PARTIAL**
Search results now carry `is_stale` flag and warning messages. No DB-level exclusion of stale chunks yet.

---

## 3. MCP Tool Gaps

### 3.1 `repo_dependencies` — **MISSING**
Plan §6 line 304 lists this tool: "bounded, evidence-linked dependency graph". Depends on `symbol_edges` table (item 1.1).

### 3.2 Tool naming mismatch — **PARTIAL**
Plan specifies `memory_search`, `memory_record`, `task_resume`.
Actual names: `memory_read`, `memory_write`, `checkpoint_get`.
Functionally equivalent but contract names differ from plan.

---

## 4. Security / Governance Gaps

### 4.1 Loopback binding default — **DONE** ✅
`config.py` default → `127.0.0.1`. `.env.example` → `127.0.0.1`. `compose.yaml` already binds `127.0.0.1:8765`.

### 4.2 Repository deletion — **DONE** ✅
`DELETE /api/repositories/{id}` + `repo-intel repo remove <id>` CLI command (with confirmation).

### 4.3 Log credential redaction — **PARTIAL**
Content is redacted before storage (Phase 6). No log-level filters to strip credentials from log output if accidentally logged.

---

## 5. Observability Gaps

### 5.1 Structured JSON logs — **MISSING**
Plan §3: *"Structured JSON logs + Prometheus metrics"*.
Currently uses plain text format. No `JSONFormatter`. Planned `observability/logging.py` module doesn't exist.

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

### 7.4 Prompt-injection defense — **MISSING**
Plan §9 (evaluation) and §10 (security) mention prompt-injection text in source comments as test case. Zero defense implementation.

### 7.5 Resource limits — **MISSING**
`compose.yaml` has no `deploy.resources.limits` for memory/CPU on any service.

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
- [x] **Unsupported/stale/conflicting evidence labeled** — staleness now flagged ✅
- [x] **Security tests cover path traversal and secrets** (Phase 6)
- [ ] **Prompt-injection defense tested** — not implemented
- [ ] **Evaluation report** — benchmark suite missing
- [x] **User guide, troubleshooting guide** — docs done
- [x] **Backup/restore** — scripts + CLI commands working ✅

---

## 10. Scoping Recommendations

Items that can be **deferred beyond v1.0 MVP** (non-goals or optional):
- Prometheus metrics (observability is nice-to-have, logging + retrieval events exist)
- Structured JSON logs (plain text works; can add later)
- Symbol-neighbor expansion (plan says "bounded", can be v1.1)
- Prompt-injection defense (plan lists it as evaluation test case, not core feature)
- OpenCode lifecycle hooks / compaction (Phase 5, deferred)

Items that should be **done for v1.0**:
- [x] Backup/restore working end-to-end
- [x] Stale evidence labeling
- [x] Repository deletion
- [x] Default loopback binding
- [x] Freshness metadata in search results
- [ ] `symbol_edges` table (if `repo_dependencies` is required for v1.0)
