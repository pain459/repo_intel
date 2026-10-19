# Remaining Work — v1.0 Gap Audit

**Date:** 2026-10-19
**Status:** Phase 10 complete. All tracked items closed. 149 tests passing, lint clean.

This document audits the implementation plan against what actually exists in the codebase.

---

## Summary

| Category          | Done | Partial | Missing |
|-------------------|------|---------|---------|
| Data Model        | 6    | 0       | 0       |
| Invariants / Indexing | 4 | 0    | 0       |
| MCP Tools         | 2    | 0       | 0       |
| Security / Governance | 5 | 0     | 0       |
| Observability     | 2    | 0       | 0       |
| CLI / Installer   | 6    | 0       | 0       |
| Retrieval Quality | 5    | 0       | 0       |
| **Total**         | **30** | **0** | **0**   |

---

## What Changed In Phases 7-10

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
| 9 | Stale chunk DB filtering | **DONE** | migration `005_phase7` |
| 10 | MCP tool naming alignment | **DONE** | `memory_search`, `memory_record`, `task_resume` resolve |
| 11 | Log credential redaction | **DONE** | `CredentialFilter` on root logger |
| 12 | Structured JSON logging | **DONE** | `log_format=json`, `JsonFormatter` |
| 13 | Prompt-injection defense | **DONE** | `prompt_guard.py` in search pipeline |
| 14 | Resource limits | **DONE** | `compose.yaml` deploy.resources.limits |
| 15 | Symbol-neighbor expansion | **DONE** | `_symbol_candidates()` in hybrid_search, 4-way RRF |
| 16 | MCP configure CLI | **DONE** | `repo-intel mcp configure` subcommand |
| 17 | Symbol edges table | **DONE** | `SymbolEdge` model, migration `006_phase10`, edge detector |
| 18 | repo_dependencies MCP tool | **DONE** | BFS graph traversal, bounded depth |
| 19 | Prometheus metrics | **DONE** | `/metrics` endpoint with search/index counters |
| 20 | Benchmark suite | **DONE** | 10 default queries, CLI + Python API |
| 21 | Evaluation docs | **DONE** | `docs/evaluation.md` |

---

## 1. Data Model — Complete

### 1.1 `symbol_edges` table — **DONE** ✅
`SymbolEdge` model with `from_symbol_id`, `to_symbol_id`, `relation_type`,
`evidence_location`, `confidence`, and `generation_id`. Migration `006_phase10`.
Unique constraint on `(from, to, relation_type)`, indexes on both directions.

### 1.2-1.4 — **DONE** ✅ (carried from Phase 7)

---

## 2. Indexing / Invariants — Complete

### 2.1-2.3 — **DONE** ✅ (carried from Phase 7)

**Plus:** Heuristic edge detector (`indexing/edge_detector.py`) scans for
Python/JS import and call patterns between known symbols. Deduplication applied.

---

## 3. MCP Tools — Complete

### 3.1 `repo_dependencies` — **DONE** ✅
BFS graph traversal tool. Parameters: `symbol_name`, `direction` (outgoing/incoming),
`depth` (max 5). Returns up to 50 edges with evidence locations.

### 3.2 — **DONE** ✅

---

## 4. Security / Governance — Complete

(All items carried from Phase 8, **DONE** ✅)

---

## 5. Observability — Complete

### 5.1 Structured JSON logs — **DONE** ✅

### 5.2 Prometheus metrics — **DONE** ✅
`/metrics` endpoint. Counters: `search_requests_total`, `index_chunks_total`.
Histogram: `search_latency_seconds`.

---

## 6. CLI / Installer — Complete

(All items carried from Phase 9, **DONE** ✅)

**Plus:** `repo-intel benchmark` CLI command for retrieval quality evaluation.

---

## 7. Retrieval Quality — Complete

(All items carried from Phases 8-9, **DONE** ✅)

---

## 8. Evaluation / Benchmarking — Complete

### 8.1 Benchmark suite — **DONE** ✅
`repo_intel/benchmark/runner.py`: 10 predefined queries, measures latency and recall.

### 8.2 Evaluation docs — **DONE** ✅
`docs/evaluation.md` describes pipeline, metrics, and v1.1 evaluation plan.

---

## 9. v1.0 Definition-of-Done Checklist

- [x] Fresh install on one supported developer machine succeeds
- [x] Mac + Ubuntu Ollama split works without tunnel or proxy
- [x] PostgreSQL persists (named volume)
- [x] Repo registration/indexing works with incremental changes
- [x] Hybrid retrieval returns bounded, correctly cited evidence
- [x] OpenCode can invoke MCP tools without overwriting model config
- [x] Cross-session checkpoint and memory retrieval works
- [ ] **Compaction continuity** — hooks not implemented (Phase 5, explicitly deferred)
- [x] Unsupported/stale/conflicting evidence labeled
- [x] Security tests cover path traversal and secrets
- [x] Log credential redaction
- [x] Prompt-injection defense tested
- [x] Benchmark suite present
- [x] User guide, troubleshooting guide
- [x] Backup/restore
- [x] MCP tool naming matches plan
- [x] Structured JSON logging
- [x] Symbol-neighbor expansion
- [x] MCP configure CLI
- [x] Symbol edges + repo_dependencies tool
- [x] Prometheus metrics endpoint
- [x] Evaluation docs

**Only remaining untracked item:** Compaction continuity (Phase 5, deferred).

---

## 10. Scoping Recommendations

Items deferred to v1.1:
- OpenCode lifecycle hooks / compaction (Phase 5, explicitly deferred)
- Ground-truth benchmark datasets (improved recall@N measurement)
- Cross-repository benchmark queries
