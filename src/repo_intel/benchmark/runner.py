"""Benchmark runner for retrieval quality evaluation.

Runs predefined queries against the indexed repository and measures
recall@N, MRR, and latency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from repo_intel.db.session import get_session_factory
from repo_intel.retrieval.search import hybrid_search
from repo_intel.retrieval.types import SearchRequest


@dataclass
class BenchmarkQuery:
    """One query in a benchmark set."""

    name: str
    query: str
    expected_chunks: list[str] = field(default_factory=list)
    category: str = "general"


@dataclass
class BenchmarkResult:
    """Result of running one benchmark query."""

    query_name: str
    latency_ms: float
    num_results: int
    recall_at_10: float = 0.0
    mrr: float = 0.0
    first_relevant_rank: int | None = None
    categories_matched: list[str] = field(default_factory=list)


# Built-in benchmark queries covering common search scenarios
DEFAULT_QUERIES: list[BenchmarkQuery] = [
    BenchmarkQuery("function_definition", "def compute_checksum"),
    BenchmarkQuery("class_lookup", "class UserRepository"),
    BenchmarkQuery("config_search", "database connection settings"),
    BenchmarkQuery("error_handling", "try except block error"),
    BenchmarkQuery("import_pattern", "import os path join"),
    BenchmarkQuery("test_discovery", "def test_ pytest"),
    BenchmarkQuery("docstring_search", "Args: return type"),
    BenchmarkQuery("dependency_check", "requirements pyproject dependencies"),
    BenchmarkQuery("api_endpoint", "async def router fastapi"),
    BenchmarkQuery("security_pattern", "credential token authenticate"),
]


async def run_benchmark(
    queries: list[BenchmarkQuery] | None = None,
    repository_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Run *queries* and return metrics."""
    query_set = queries or DEFAULT_QUERIES
    factory = get_session_factory()
    results: list[BenchmarkResult] = []
    total_latency = 0.0

    async with factory() as session:
        for bq in query_set:
            t0 = time.monotonic()
            request = SearchRequest(
                query=bq.query,
                repository_id=repository_id,
                limit=limit,
            )
            hits = await hybrid_search(session, request)
            elapsed_ms = (time.monotonic() - t0) * 1000
            total_latency += elapsed_ms

            recall = 0.0
            mrr = 0.0
            first_rank: int | None = None
            if bq.expected_chunks:
                hit_ids = [str(h.chunk_id) for h in hits]
                found = sum(1 for cid in bq.expected_chunks if cid in hit_ids)
                recall = found / len(bq.expected_chunks)
                # MRR: reciprocal rank of first relevant hit
                for rank_idx, hid in enumerate(hit_ids, 1):
                    if hid in bq.expected_chunks:
                        first_rank = rank_idx
                        mrr = 1.0 / rank_idx
                        break

            methods: set[str] = set()
            for h in hits:
                methods.update(h.retrieval_methods)

            results.append(BenchmarkResult(
                query_name=bq.name,
                latency_ms=round(elapsed_ms, 2),
                num_results=len(hits),
                recall_at_10=recall,
                mrr=mrr,
                first_relevant_rank=first_rank,
                categories_matched=list(methods),
            ))

    avg_latency = (
        total_latency / len(results) if results else 0.0
    )

    average_mrr = (
        sum(r.mrr for r in results) / len(results) if results else 0.0
    )

    return {
        "num_queries": len(query_set),
        "avg_latency_ms": round(avg_latency, 2),
        "total_latency_ms": round(total_latency, 2),
        "average_mrr": round(average_mrr, 4),
        "results": [
            {
                "query": r.query_name,
                "latency_ms": r.latency_ms,
                "num_results": r.num_results,
                "recall_at_10": r.recall_at_10,
                "mrr": r.mrr,
                "first_relevant_rank": r.first_relevant_rank,
                "methods": r.categories_matched,
            }
            for r in results
        ],
    }
