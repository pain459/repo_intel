# Evaluation — Retrieval Quality

**repo_intel v1.0**

This document describes how to evaluate the retrieval quality of the hybrid
search pipeline and the benchmark suite that ships with the project.

---

## 1. Architecture

repo_intel uses a **4-way hybrid retrieval** pipeline:

| Rank | Method    | What It Does                                    |
|------|-----------|--------------------------------------------------|
| 1    | exact     | Exact substring match on chunk content            |
| 2    | lexical   | PostgreSQL full-text search (FTS)                 |
| 3    | semantic  | pgvector cosine-similarity against embeddings     |
| 4    | symbol    | Symbol-name expansion for identifier queries      |

Results from each sub-search are fused using **Reciprocal Rank Fusion (RRF)**
with `k = 60`.

### Query Sanitization

Before any search method runs, queries pass through the prompt-injection
guard (`security/prompt_guard.py`). Adversarial patterns are detected and
stripped; fully adversarial queries return zero results.

---

## 2. Metrics

| Metric         | Description                                      |
|----------------|--------------------------------------------------|
| `recall@10`    | Fraction of expected chunks found in top-10      |
| `mean_latency`  | Average query latency (ms) across benchmark set |
| `latency_p95`  | 95th-percentile query latency (ms)                |
| `coverage`     | Fraction of queries returning ≥ 1 result          |

---

## 3. Running the Benchmark

### CLI

```bash
repo-intel benchmark

# Scoped to a specific repository
repo-intel benchmark --repository-id <uuid>

# Custom result limit
repo-intel benchmark -r <uuid> -l 20
```

The benchmark runs 10 predefined queries covering common developer intents:
function lookups, class searches, config patterns, error handling, imports,
test discovery, docstrings, dependencies, API endpoints, and security.

### Python API

```python
from repo_intel.benchmark.runner import run_benchmark

result = await run_benchmark(limit=10)
print(result["avg_latency_ms"])
```

---

## 4. Prometheus Metrics

A `/metrics` endpoint is available when the FastAPI server is running:

```bash
curl http://127.0.0.1:8765/metrics
```

Key metrics:
- `repo_intel_search_requests_total` — counter, labelled by method
- `repo_intel_search_latency_seconds` — histogram of query latency
- `repo_intel_index_chunks_total` — counter of indexed chunks by type

---

## 5. Dependency Graph

The `symbol_edges` table stores heuristic dependency edges between symbols
detected from source files (imports, calls). The `repo_dependencies` MCP
tool traverses this graph:

```
repo_dependencies("UserRepository", direction="outgoing", depth=2)
```

This returns up to 50 edges with evidence locations and confidence scores.

---

## 6. v1.1 Evaluation Plan

Items deferred to v1.1 for a more thorough evaluation:

1. **Ground-truth datasets** — seed known answer sets per query class
2. **MRR@N** — mean reciprocal rank for top-N precision
3. **Token efficiency** — ratio of useful tokens to total returned tokens
4. **Cross-repository queries** — benchmark across multiple repos
5. **Freshness impact** — measure recall degradation vs index age
