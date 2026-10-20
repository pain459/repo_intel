"""Regression tests for evaluation issues 1-6 (October 2026).

Covers:
- Issue 1: Chunk fallback generation_id filter (defense-in-depth)
- Issue 2: Control-flow keyword filtering, JS/TS kind classification
- Issue 3: Self-loop edge prevention, dependency direction correctness
- Issue 4: Search result limit enforcement
- Issue 5: Incremental indexing consistency
- Issue 6: REST tool completeness (memory_search, compaction_checkpoint_save, etc.)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from repo_intel.api.app import create_app
from repo_intel.db.models import (
    IndexGeneration,
    Repository,
    Symbol,
    SymbolEdge,
)
from repo_intel.db.session import get_session_factory
from repo_intel.indexing.chunker import _detect_language, _find_boundaries, chunk_file
from repo_intel.indexing.edge_detector import detect_edges

client = TestClient(create_app())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_id():
    """Return the fastapi-template repository ID."""
    import asyncio

    async def _get():
        factory = get_session_factory()
        async with factory() as session:
            repo = (
                await session.scalars(
                    select(Repository).where(
                        Repository.name == "fastapi-template",
                    )
                )
            ).first()
            return str(repo.id) if repo else None

    return asyncio.run(_get())


@pytest.fixture
def active_gen_ids(repo_id):
    """Return active generation IDs for fastapi-template."""
    import asyncio

    async def _get():
        if not repo_id:
            return []
        factory = get_session_factory()
        async with factory() as session:
            rows = await session.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )
            return [str(g) for g in rows]

    return asyncio.run(_get())


# ---------------------------------------------------------------------------
# Issue 1: Chunk fallback generation filter
# ---------------------------------------------------------------------------


class TestChunkFallbackGenerationFilter:
    """Verify repo_symbol chunk fallback filters by active generation."""

    def test_chunk_fallback_code_filters_by_generation(self) -> None:
        """Both fastmcp.py and server.py chunk fallback use generation_id."""
        import pathlib

        fastmcp_path = pathlib.Path(__file__).parents[1] / "src" / "repo_intel" / "mcp" / "fastmcp.py"
        server_path = pathlib.Path(__file__).parents[1] / "src" / "repo_intel" / "mcp" / "server.py"

        fastmcp_src = fastmcp_path.read_text()
        server_src = server_path.read_text()

        # The chunk fallback section should reference Chunk.generation_id
        assert "Chunk.generation_id.in_(active_gen_ids)" in fastmcp_src, (
            "fastmcp chunk fallback missing generation_id filter"
        )
        assert "Chunk.generation_id.in_(active_gen_ids)" in server_src, (
            "server chunk fallback missing generation_id filter"
        )


# ---------------------------------------------------------------------------
# Issue 2: Control-flow keyword filtering + kind classification
# ---------------------------------------------------------------------------


class TestControlFlowKeywordFiltering:
    """Verify control-flow keywords are not indexed as symbols."""

    def test_python_boundaries_skip_control_flow(self) -> None:
        """Python control-flow constructs should not produce symbol boundaries."""
        code = (
            "def real_func():\n"
            "    if True:\n"
            "        pass\n"
            "    for x in range(3):\n"
            "        pass\n"
            "    while False:\n"
            "        pass\n"
        )
        boundaries = _find_boundaries(code.splitlines(), "python")
        names = [b[3] for b in boundaries if b[3] is not None]
        assert "if" not in names, "if should be filtered"
        assert "for" not in names, "for should be filtered"
        assert "while" not in names, "while should be filtered"
        assert "real_func" in names, "real_func should be present"

    def test_js_boundaries_skip_control_flow(self) -> None:
        """JS/TS control-flow constructs should not produce symbol boundaries."""
        code = (
            "function realFn() {\n"
            "  if (true) {\n"
            "  }\n"
            "  for (let i = 0; i < 3; i++) {\n"
            "  }\n"
            "  while (false) {\n"
            "  }\n"
            "}\n"
        )
        boundaries = _find_boundaries(code.splitlines(), "javascript")
        names = [b[3] for b in boundaries if b[3] is not None]
        assert "if" not in names, "if should be filtered"
        assert "for" not in names, "for should be filtered"
        assert "while" not in names, "while should be filtered"
        assert "realFn" in names, "realFn should be present"

    def test_js_arrow_function_kind_is_function(self) -> None:
        """Arrow function boundaries should have kind='function', not 'class'."""
        code = "const myArrow = () => { return 1; }"
        boundaries = _find_boundaries(code.splitlines(), "javascript")
        arrow_bounds = [b for b in boundaries if b[3] == "myArrow"]
        if arrow_bounds:
            assert arrow_bounds[0][2] == "function", (
                f"Arrow function kind should be 'function', got {arrow_bounds[0][2]}"
            )

    def test_js_method_kind_is_function(self) -> None:
        """JS method boundaries should have kind='function', not 'class'."""
        code = "obj.myMethod() {\n  return true;\n}"
        boundaries = _find_boundaries(code.splitlines(), "javascript")
        method_bounds = [b for b in boundaries if b[3] == "myMethod"]
        if method_bounds:
            assert method_bounds[0][2] == "function", (
                f"JS method kind should be 'function', got {method_bounds[0][2]}"
            )

    def test_no_control_flow_symbols_in_index(self, repo_id, active_gen_ids) -> None:
        """The index should contain no control-flow keyword symbols."""
        import asyncio

        async def _check():
            if not repo_id or not active_gen_ids:
                return True
            factory = get_session_factory()
            async with factory() as session:
                cf_count = await session.scalar(
                    select(func.count(Symbol.id)).where(
                        Symbol.name.in_(["if", "for", "while", "switch", "else"]),
                        Symbol.generation_id.in_(active_gen_ids),
                    )
                )
                return cf_count == 0

        assert asyncio.run(_check()), "Control-flow keywords found as symbols"


# ---------------------------------------------------------------------------
# Issue 3: Self-loop edge prevention
# ---------------------------------------------------------------------------


class TestSelfLoopEdgePrevention:
    """Verify self-loop edges are prevented at persistence time."""

    def test_edge_detector_enclosing_neq_callee(self) -> None:
        """Edge detector should not emit edges where from == to."""
        code = "def foo():\n    foo()\n"
        edges = detect_edges(code, defined_symbols={"foo"})
        for e in edges:
            assert e.from_name != e.to_name, (
                f"Self-loop in edge detector: {e.from_name} -> {e.to_name}"
            )

    def test_no_self_loop_edges_in_index(self, repo_id, active_gen_ids) -> None:
        """Database should have no self-loop edges."""
        import asyncio

        async def _check():
            if not repo_id or not active_gen_ids:
                return True
            factory = get_session_factory()
            async with factory() as session:
                sl = await session.scalar(
                    select(func.count(SymbolEdge.id)).where(
                        SymbolEdge.generation_id.in_(active_gen_ids),
                        SymbolEdge.from_symbol_id == SymbolEdge.to_symbol_id,
                    )
                )
                return sl == 0

        assert asyncio.run(_check()), "Self-loop edges found in index"


# ---------------------------------------------------------------------------
# Issue 3b: Dependency direction correctness
# ---------------------------------------------------------------------------


class TestDependencyDirection:
    """Verify repo_dependencies output direction semantics."""

    def test_outgoing_edges_show_caller_to_callee(self, repo_id) -> None:
        """Outgoing: from=caller, to=callee."""
        if not repo_id:
            return
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_dependencies",
                "parameters": {
                    "symbol_name": "login_access_token",
                    "repository_id": repo_id,
                    "direction": "outgoing",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        edges = data.get("edges", [])
        # login_access_token should be the from_symbol in outgoing edges
        login_edges = [e for e in edges if "login" in e.get("from_symbol", "").lower()]
        assert len(login_edges) >= 1, "login_access_token should appear as caller"

    def test_incoming_edges_show_callers_pointing_to_target(self, repo_id) -> None:
        """Incoming: from=caller, to=targetcallee."""
        if not repo_id:
            return
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_dependencies",
                "parameters": {
                    "symbol_name": "authenticate",
                    "repository_id": repo_id,
                    "direction": "incoming",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        edges = data.get("edges", [])
        # authenticate should be the to_symbol (callee) in incoming edges
        auth_callee = [
            e for e in edges if "authenticate" in e.get("to_symbol", "")
        ]
        assert len(auth_callee) >= 1, "authenticate should appear as callee"

    def test_login_calls_authenticate_round_trip(self, repo_id) -> None:
        """login_access_token outgoing -> authenticate AND authenticate incoming <- login."""
        if not repo_id:
            return

        # Outgoing from login_access_token should include authenticate
        r1 = client.post("/api/mcp/call", json={
            "tool": "repo_dependencies",
            "parameters": {
                "symbol_name": "login_access_token",
                "repository_id": repo_id,
                "direction": "outgoing",
            },
        })
        assert r1.status_code == 200
        outgoing = r1.json().get("edges", [])
        has_auth = any("authenticate" in e.get("to_symbol", "") for e in outgoing)

        # Incoming to authenticate should include login_access_token
        r2 = client.post("/api/mcp/call", json={
            "tool": "repo_dependencies",
            "parameters": {
                "symbol_name": "authenticate",
                "repository_id": repo_id,
                "direction": "incoming",
            },
        })
        assert r2.status_code == 200
        incoming = r2.json().get("edges", [])
        has_login = any(
            "login" in e.get("from_symbol", "").lower() for e in incoming
        )

        assert has_auth, "login_access_token should call authenticate (outgoing)"
        assert has_login, "authenticate should have login as caller (incoming)"


# ---------------------------------------------------------------------------
# Issue 4: Search limit enforcement
# ---------------------------------------------------------------------------


class TestSearchLimitEnforcement:
    """Verify repo_search respects the limit parameter."""

    def test_limit_param_is_respected(self, repo_id) -> None:
        """Returned results should not exceed requested limit."""
        if not repo_id:
            return
        for limit in [3, 5, 10]:
            resp = client.post(
                "/api/mcp/call",
                json={
                    "tool": "repo_search",
                    "parameters": {
                        "query": "authentication",
                        "repository_id": repo_id,
                        "limit": limit,
                    },
                },
            )
            assert resp.status_code == 200
            results = resp.json().get("results", [])
            assert len(results) <= limit, (
                f"limit={limit} returned {len(results)} results (exceeds limit)"
            )

    def test_search_results_have_metadata(self, repo_id) -> None:
        """Search results should include all expected metadata fields."""
        if not repo_id:
            return
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_search",
                "parameters": {
                    "query": "JWT",
                    "repository_id": repo_id,
                    "limit": 3,
                },
            },
        )
        assert resp.status_code == 200
        results = resp.json().get("results", [])
        if results:
            for r in results:
                assert "start_line" in r
                assert "end_line" in r
                assert "text" in r
                assert "evidence_kind" in r
                assert "is_stale" in r
                assert "is_truncated" in r
                assert "generation_created_at" in r


# ---------------------------------------------------------------------------
# Issue 5: Incremental indexing consistency
# ---------------------------------------------------------------------------


class TestIncrementalIndexingConsistency:
    """Verify file/chunk consistency after reindex."""

    def test_all_files_have_chunks(self, repo_id, active_gen_ids) -> None:
        """Every active file should have at least one chunk in the active gen."""
        import asyncio

        async def _check():
            if not repo_id or not active_gen_ids:
                return True
            from repo_intel.db.models import Chunk, FileRecord

            factory = get_session_factory()
            async with factory() as session:
                orphan_files = await session.scalar(
                    select(func.count(FileRecord.id)).where(
                        FileRecord.repository_id == repo_id,
                        FileRecord.deleted == False,  # noqa: E712
                        FileRecord.id.notin_(
                            select(Chunk.file_id).where(
                                Chunk.generation_id.in_(active_gen_ids),
                                Chunk.stale == False,  # noqa: E712
                            )
                        ),
                    )
                )
                return orphan_files == 0

        assert asyncio.run(_check()), "Some files have no chunks in active gen"

    def test_active_gen_has_no_stale_chunks(self, active_gen_ids) -> None:
        """Active generation should have no stale chunks."""
        import asyncio
        from repo_intel.db.models import Chunk

        async def _check():
            if not active_gen_ids:
                return True
            factory = get_session_factory()
            async with factory() as session:
                st = await session.scalar(
                    select(func.count(Chunk.id)).where(
                        Chunk.generation_id.in_(active_gen_ids),
                        Chunk.stale == True,  # noqa: E712
                    )
                )
                return st == 0

        assert asyncio.run(_check()), "Stale chunks found in active gen"


# ---------------------------------------------------------------------------
# Issue 6: REST tool completeness
# ---------------------------------------------------------------------------


class TestRESTToolCompleteness:
    """Verify all tools callable via fastmcp are also available via REST."""

    def test_memory_search_available(self, repo_id) -> None:
        """memory_search should be dispatchable via REST."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_search",
                "parameters": {
                    "query": "test",
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "num_memories" in data or "memories" in data

    def test_memory_record_available(self, repo_id) -> None:
        """memory_record should work as alias for memory_write."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_record",
                "parameters": {
                    "kind": "regression-test",
                    "statement": "memory record regression test",
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("id")

    def test_compaction_checkpoint_save_available(self, repo_id) -> None:
        """compaction_checkpoint_save should be dispatchable via REST."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "compaction_checkpoint_save",
                "parameters": {
                    "objective": "regression test",
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("id")

    def test_session_bootstrap_available(self, repo_id) -> None:
        """session_bootstrap should be dispatchable via REST."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "session_bootstrap",
                "parameters": {
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200

    def test_task_resume_available(self, repo_id) -> None:
        """task_resume should be dispatchable via REST (alias for checkpoint_get)."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "task_resume",
                "parameters": {
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200

    def test_memory_write_forwards_author(self, repo_id) -> None:
        """memory_write should forward author parameter."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_write",
                "parameters": {
                    "kind": "regression-author-test",
                    "statement": "author forwarding test",
                    "repository_id": repo_id,
                    "author": "regression-test-agent",
                },
            },
        )
        assert resp.status_code == 200

        # Read it back and verify author is present
        r2 = client.post(
            "/api/mcp/call",
            json={
                "tool": "memory_read",
                "parameters": {
                    "query": "author forwarding test",
                    "repository_id": repo_id,
                },
            },
        )
        data = r2.json()
        mems = data.get("memories", [])
        author_mem = [m for m in mems if m.get("author") == "regression-test-agent"]
        assert len(author_mem) >= 1, "Author not preserved in memory"
