# v1.0 Gap Audit — Complete

**Date:** 2026-10-19
**Status:** Phase 10 (compaction) complete. All items closed. 154 tests passing, lint clean.

This document audits the implementation plan against what actually exists in the codebase.

---

## Summary

| Category          | Done | Partial | Missing |
|-------------------|------|---------|---------|
| Data Model        | 6    | 0       | 0       |
| Invariants / Indexing | 4 | 0    | 0       |
| MCP Tools         | 3    | 0       | 0       |
| Security / Governance | 5 | 0     | 0       |
| Observability     | 2    | 0       | 0       |
| CLI / Installer   | 6    | 0       | 0       |
| Retrieval Quality | 5    | 0       | 0       |
| Context Continuity | 4   | 0       | 0       |
| **Total**         | **35** | **0** | **0**   |

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
| 22 | Compaction continuity | **DONE** | Auto-checkpoint scheduler, stale invalidation, `session_bootstrap` MCP tool, `compaction_checkpoint_save` MCP tool |

---

## 1. Data Model — Complete

### 1.1 `symbol_edges` table — **DONE** ✅
`SymbolEdge` model with `from_symbol_id`, `to_symbol_id`, `relation_type`,
`evidence_location`, `confidence`, and `generation_id`. Migration `006_phase10`.

### 1.2-1.4 — **DONE** ✅ (carried from Phase 7)

---

## 2. Indexing / Invariants — Complete

### 2.1-2.3 — **DONE** ✅ (carried from Phase 7)

**Plus:** Heuristic edge detector (`indexing/edge_detector.py`) scans for
Python/JS import and call patterns between known symbols.

---

## 3. MCP Tools — Complete

### 3.1 `repo_dependencies` — **DONE** ✅
BFS graph traversal tool.

### 3.2 `compaction_checkpoint_save` — **DONE** ✅
Save checkpoint optimized for compaction recovery. Tags with compaction marker.

### 3.3 `session_bootstrap` — **DONE** ✅
Restore session state + verified memories after compaction or restart.

### 3.4 — **DONE** ✅

---

## 4. Security / Governance — Complete

(All items carried from Phase 8, **DONE** ✅)

---

## 5. Observability — Complete

(All items carried, **DONE** ✅)

---

## 6. CLI / Installer — Complete

(All items carried from Phase 9, **DONE** ✅)

---

## 7. Retrieval Quality — Complete

(All items carried from Phases 8-9, **DONE** ✅)

---

## 8. Evaluation / Benchmarking — Complete

(All items carried, **DONE** ✅)

---

## 9. Context Continuity (Phase 5) — Complete

### 9.1 Auto-checkpoint scheduler — **DONE** ✅
`AutoCheckpointScheduler` starts in app lifespan, periodically marks old
checkpoints stale (15 min interval, 4 hour stale threshold).

### 9.2 Stale-checkpoint invalidation — **DONE** ✅
Checkpoints older than threshold are tagged in their `evidence.compaction`
dict with `marked_stale_at`. Agents can skip stale checkpoints on resume.

### 9.3 Session resume bootstrap — **DONE** ✅
`session_bootstrap` MCP tool returns the latest checkpoint + verified
memories, scoped to session/repository. No OpenCode lifecycle hooks needed.

### 9.4 Compaction checkpoint save — **DONE** ✅
`compaction_checkpoint_save` MCP tool: explicit save-before-compaction that
tags checkpoints with a compaction marker for easy identification.

---

## 10. v1.0 Definition-of-Done Checklist

- [x] Fresh install on one supported developer machine succeeds
- [x] Mac + Ubuntu Ollama split works without tunnel or proxy
- [x] PostgreSQL persists (named volume)
- [x] Repo registration/indexing works with incremental changes
- [x] Hybrid retrieval returns bounded, correctly cited evidence
- [x] OpenCode can invoke MCP tools without overwriting model config
- [x] Cross-session checkpoint and memory retrieval works
- [x] **Compaction continuity** — auto-checkpoint scheduler, stale invalidation, session bootstrap
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

**All items checked. v1.0 Definition-of-Done achieved.**

---

## 11. v1.1 Scoping

Items for future consideration:
- Ground-truth benchmark datasets (improved recall@N measurement)
- Cross-repository benchmark queries
- OpenCode lifecycle hooks (optional, if the platform exposes stable hooks)
- Token-efficient context-pack generation
