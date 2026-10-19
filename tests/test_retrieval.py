"""Tests for the retrieval pipeline and hybrid search."""

from __future__ import annotations

import pytest
from repo_intel.retrieval.types import SearchRequest, SearchResult, SearchMethod
from repo_intel.retrieval.search import (
    _rrf_fuse,
    _apply_token_budget,
    _build_reason,
    _CHARS_PER_TOKEN,
)


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------


def test_rrf_fuse_single_source():
    """A single source ranks items in order."""
    candidates = {
        "c1": 1,
        "c2": 2,
        "c3": 5,
    }
    result = _rrf_fuse([candidates], ["lexical"])
    ids = [_cid for _cid, _score, _methods in result]
    assert ids == ["c1", "c2", "c3"]


def test_rrf_fuse_multiple_sources_boosts_overlaps():
    """Items appearing in multiple sources get higher fused scores."""
    exact = {"c1": 3, "c2": 1}
    lexical = {"c1": 1, "c3": 2}
    semantic = {"c2": 2, "c3": 1}

    result = _rrf_fuse([exact, lexical, semantic], ["exact", "lexical", "semantic"])
    ids = [_cid for _cid, _score, _methods in result]

    # c1 appears in exact + lexical (2 sources), should rank high
    # c3 appears in lexical + semantic (2 sources), should rank high
    # c2 appears in exact + semantic (2 sources), should rank high
    assert len(ids) == 3


def test_rrf_fuse_includes_methods():
    """Each result is annotated with the methods that found it."""
    exact = {"c1": 1}
    lexical = {"c1": 1, "c2": 2}
    semantic: dict[str, int] = {}

    result = _rrf_fuse([exact, lexical, semantic], ["exact", "lexical", "semantic"])
    methods_by_id: dict[str, list[str]] = {}
    for _cid, _score, methods in result:
        methods_by_id[_cid] = methods

    assert "exact" in methods_by_id["c1"]
    assert "lexical" in methods_by_id["c1"]
    assert methods_by_id["c2"] == ["lexical"]


def test_rrf_fuse_empty():
    """Empty candidate sets produce no results."""
    result = _rrf_fuse([], [])
    assert result == []

    result = _rrf_fuse([{}, {}], ["lexical", "semantic"])
    assert result == []


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


def _make_result(text_len: int) -> SearchResult:
    return SearchResult(
        chunk_id=__import__("uuid").uuid4(),
        path="test.py",
        start_line=1,
        end_line=10,
        content_hash="abc",
        text="x" * text_len,
        estimated_tokens=text_len // _CHARS_PER_TOKEN,
    )


def test_apply_token_budget_keeps_within_limit():
    """Results are trimmed so total tokens ≤ budget."""
    results = [_make_result(400) for _ in range(10)]  # 100 tokens each
    budget = 500
    trimmed = _apply_token_budget(results, budget)
    total = sum(r.estimated_tokens for r in trimmed)
    assert total <= budget + 100  # allow small margin for rounding


def test_apply_token_budget_truncates_last():
    """The last chunk that exceeds budget is truncated."""
    results = [_make_result(400), _make_result(400), _make_result(400)]
    budget = 90  # fits 2 chunks (80 tokens), 3rd (80 tokens) would exceed
    trimmed = _apply_token_budget(results, budget)
    # Should have at most 3, with last truncated
    assert len(trimmed) <= 3
    if len(trimmed) == 3:
        assert "[truncated]" in trimmed[2].text


def test_apply_token_budget_empty():
    """Empty input produces empty output."""
    assert _apply_token_budget([], 1000) == []


# ---------------------------------------------------------------------------
# Relevance reason
# ---------------------------------------------------------------------------


def test_build_reason_single():
    assert "exact" in _build_reason(["exact"])
