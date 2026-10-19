"""Tests for the benchmark runner."""

from __future__ import annotations

import pytest

from repo_intel.benchmark.runner import (
    DEFAULT_QUERIES,
    BenchmarkQuery,
    run_benchmark,
)


def test_default_queries_exist() -> None:
    assert len(DEFAULT_QUERIES) >= 5
    for q in DEFAULT_QUERIES:
        assert isinstance(q, BenchmarkQuery)
        assert q.name
        assert q.query


@pytest.mark.asyncio
async def test_benchmark_runs() -> None:
    """run_benchmark returns a dict with expected keys."""
    result = await run_benchmark(limit=2)
    assert "num_queries" in result
    assert "avg_latency_ms" in result
    assert "results" in result
    assert isinstance(result["results"], list)
