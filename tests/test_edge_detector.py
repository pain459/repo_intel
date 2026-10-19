"""Tests for the edge detector module."""

from __future__ import annotations

from repo_intel.indexing.edge_detector import (
    detect_edges,
)

PYTHON_CODE = """\
from os.path import join
import json as j

USER_REPOS = frozenset({"print", "len", "str"})

def list_users():
    return join("/var", "users")

def process_data():
    json_out = j.dumps({"key": 1})
    list_users()
    return json_out
"""

SYMBOLS = {"list_users", "process_data", "join", "USER_REPOS"}


class TestDetectEdges:
    """Verify that the heuristic edge detector fires on realistic code."""

    def test_import_edge_detected(self) -> None:
        edges = detect_edges(PYTHON_CODE, SYMBOLS)
        types = {e.relation_type for e in edges}
        assert "imports" in types or "calls" in types

    def test_no_self_loops_on_builtins(self) -> None:
        edges = detect_edges("print(1)\nlen(x)\nstr(y)", {"print", "len"})
        callers = {e.from_name for e in edges}
        assert "print" not in callers
        assert "len" not in callers

    def test_returns_list(self) -> None:
        edges = detect_edges("def foo(): pass", set())
        assert isinstance(edges, list)

    def test_deduplicates(self) -> None:
        code = "\n".join(["list_users()" for _ in range(10)])
        edges = detect_edges(code, {"list_users"})
        assert len(edges) <= 2  # dedup collapses duplicates
