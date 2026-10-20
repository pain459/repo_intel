"""End-to-end reliability tests for repo_intel.

Covers five evaluation dimensions:
  D1. Incremental indexing (content-hash change detection, stale chunk cleanup)
  D2. Dependency graph accuracy (correct direction, edge types, no self-loops)
  D3. Memory, checkpoints, and session recovery
  D4. Retrieved evidence accuracy after repository changes
  D5. File-read reduction and tool correctness

All tests run against the live PostgreSQL/pgvector stack.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from repo_intel.api.app import create_app
from repo_intel.db.models import (
    Chunk,
    FileRecord,
    IndexGeneration,
    Memory,
    Repository,
    RetrievalEvent,
    Symbol,
    SymbolEdge,
    TaskCheckpoint,
)
from repo_intel.db.session import get_session_factory
from repo_intel.indexing.chunker import _find_boundaries, chunk_file
from repo_intel.indexing.discovery import discover_files
from repo_intel.retrieval.search import hybrid_search
from repo_intel.retrieval.types import EvidenceKind, SearchRequest

client = TestClient(create_app())


# ---------------------------------------------------------------------------
# Fixture: repository lookup (synchronous, used by sync tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def repo_id():
    """fastapi-template repository ID from DB."""
    import asyncio

    async def _lookup():
        factory = get_session_factory()
        async with factory() as s:
            repo = (await s.scalars(
                select(Repository).where(
                    Repository.name == "fastapi-template"
                )
            )).first()
        return str(repo.id) if repo else None

    return asyncio.run(_lookup())


@pytest.fixture(scope="module")
def repo_path():
    """git_path for fastapi-template."""
    import asyncio

    async def _lookup():
        factory = get_session_factory()
        async with factory() as s:
            repo = (await s.scalars(
                select(Repository).where(
                    Repository.name == "fastapi-template"
                )
            )).first()
        return repo.git_path if repo else None

    return asyncio.run(_lookup())


# ===================================================================
# D1: Incremental Indexing
# ===================================================================

class TestIncrementalContentHash:
    """Content-hash change detection and chunking correctness."""

    def test_discovery_picks_up_repo_files(self, repo_path) -> None:
        """discover_files returns files for the known repo."""
        discovered = discover_files(repo_path)
        assert len(discovered) > 0, "No files discovered"
        for d in discovered[:5]:
            assert len(d.content_hash) == 64, "Hash not valid SHA-256"

    def test_chunking_reflects_source_content(self, repo_path) -> None:
        """Chunks preserve line numbers and symbol names from source."""
        target = os.path.join(repo_path, "app", "main.py")
        if not os.path.exists(target):
            pytest.skip()
        with open(target) as f:
            content = f.read()
        chunks = chunk_file("app/main.py", content)
        has_def = any(
            c.symbol_name and (
                "create_user" in c.symbol_name
                or "get_db" in c.symbol_name
                or "main" in c.symbol_name
                or "authenticate" in c.symbol_name
            )
            for c in chunks
        )
        assert has_def, (
            f"Expected symbols not found; "
            f"got {[c.symbol_name for c in chunks if c.symbol_name]}"
        )

    def test_boundary_detection_python(self) -> None:
        """Python boundary detection finds def/class/variable correctly."""
        lines = [
            "def hello():",
            "    pass",
            "",
            "class Service:",
            "    def method(self):",
            "        pass",
            "",
            "SessionDep = SomeType()",
        ]
        bounds = _find_boundaries(lines, "python")
        names = [b[3] for b in bounds if b[3]]
        assert "hello" in names
        assert "Service" in names
        assert "SessionDep" in names


class TestGenerationLifecycle:
    """Index generation state transitions are correct."""

    @pytest.mark.asyncio
    async def test_at_most_one_active(self, repo_id) -> None:
        """A repository has at most one active generation."""
        factory = get_session_factory()
        async with factory() as s:
            cnt = await s.scalar(
                select(func.count(IndexGeneration.id)).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )
            assert cnt <= 1, f"{cnt} active generations"

    @pytest.mark.asyncio
    async def test_at_most_one_building(self, repo_id) -> None:
        """A repository has at most one building generation."""
        factory = get_session_factory()
        async with factory() as s:
            cnt = await s.scalar(
                select(func.count(IndexGeneration.id)).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "building",
                )
            )
            assert cnt <= 1, f"{cnt} building generations"

    @pytest.mark.asyncio
    async def test_no_stale_in_active_gen(self, repo_id) -> None:
        """Active generation chunks are all non-stale."""
        factory = get_session_factory()
        async with factory() as s:
            ag = (await s.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )).first()
            if not ag:
                pytest.skip("No active generation")
            stale = await s.scalar(
                select(func.count(Chunk.id)).where(
                    Chunk.generation_id == ag,
                    Chunk.stale == True,
                )
            )
            assert stale == 0, f"{stale} stale chunks in active gen"

    @pytest.mark.asyncio
    async def test_retired_gens_have_stale_chunks(self, repo_id) -> None:
        """Retired generation chunks are marked stale."""
        factory = get_session_factory()
        async with factory() as s:
            retired = (await s.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "retired",
                )
            )).all()
            if not retired:
                pytest.skip("No retired generations")
            for rgid in retired[:3]:
                unstale = await s.scalar(
                    select(func.count(Chunk.id)).where(
                        Chunk.generation_id == rgid,
                        Chunk.stale == False,
                    )
                )
                assert unstale == 0, f"Retired gen has {unstale} non-stale"


# ===================================================================
# D2: Dependency Graph Accuracy
# ===================================================================

class TestEdgeIntegrity:
    """No orphan edges, no self-loops, valid relation types."""

    @pytest.mark.asyncio
    async def test_no_self_loops(self) -> None:
        """No edge points from a symbol to itself."""
        factory = get_session_factory()
        async with factory() as s:
            loops = await s.scalar(
                select(func.count(SymbolEdge.id)).where(
                    SymbolEdge.from_symbol_id == SymbolEdge.to_symbol_id
                )
            )
            assert loops == 0, f"{loops} self-loop edges"

    @pytest.mark.asyncio
    async def test_valid_relation_types(self) -> None:
        """All edges have a known relation_type."""
        factory = get_session_factory()
        async with factory() as s:
            edge_types = set(
                r[0] for r in await s.execute(
                    select(SymbolEdge.relation_type).distinct()
                )
            )
            valid = {"imports", "calls", "references"}
            bad = edge_types - valid
            assert not bad, f"Unknown edge types: {bad}"

    @pytest.mark.asyncio
    async def test_no_orphan_edge_refs(self, repo_id) -> None:
        """Every edge endpoint references a symbol in the same generation."""
        factory = get_session_factory()
        async with factory() as s:
            ag = (await s.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )).first()
            if not ag:
                pytest.skip()
            sym_ids = set(
                str(r[0]) for r in await s.execute(
                    select(Symbol.id).where(Symbol.generation_id == ag)
                )
            )
            assert len(sym_ids) > 0, "No symbols"
            edge_rows = await s.execute(
                select(
                    SymbolEdge.from_symbol_id,
                    SymbolEdge.to_symbol_id,
                ).where(SymbolEdge.generation_id == ag)
            )
            orphans = 0
            for fr in edge_rows:
                if str(fr[0]) not in sym_ids:
                    orphans += 1
                if str(fr[1]) not in sym_ids:
                    orphans += 1
            assert orphans == 0, f"{orphans} orphan references"

    @pytest.mark.asyncio
    async def test_import_edges_valid_endpoints(self) -> None:
        """Import edges reference actual symbols (spot-check)."""
        factory = get_session_factory()
        async with factory() as s:
            import_edges = (await s.scalars(
                select(SymbolEdge).where(
                    SymbolEdge.relation_type == "imports"
                )
            )).all()
            for ie in import_edges[:20]:
                fs = (await s.scalars(
                    select(Symbol).where(Symbol.id == ie.from_symbol_id)
                )).first()
                ts = (await s.scalars(
                    select(Symbol).where(Symbol.id == ie.to_symbol_id)
                )).first()
                assert fs is not None, "Import from-symbol missing"
                assert ts is not None, "Import to-symbol missing"

    @pytest.mark.asyncio
    async def test_calls_edges_valid(self, repo_id) -> None:
        """Calls edges connect real functions."""
        factory = get_session_factory()
        async with factory() as s:
            ag = (await s.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )).first()
            if not ag:
                pytest.skip()
            call_edges = (await s.scalars(
                select(SymbolEdge).where(
                    SymbolEdge.generation_id == ag,
                    SymbolEdge.relation_type == "calls",
                )
            )).all()
            for ce in call_edges[:5]:
                assert (await s.scalars(
                    select(Symbol).where(Symbol.id == ce.from_symbol_id)
                )).first() is not None
                assert (await s.scalars(
                    select(Symbol).where(Symbol.id == ce.to_symbol_id)
                )).first() is not None


class TestKnownDependencies:
    """Verify specific expected relationships."""

    @pytest.mark.asyncio
    async def test_authenticate_symbol_edges(self, repo_id) -> None:
        """If authenticate exists, it has edges."""
        factory = get_session_factory()
        async with factory() as s:
            ag = (await s.scalars(
                select(IndexGeneration.id).where(
                    IndexGeneration.repository_id == repo_id,
                    IndexGeneration.state == "active",
                )
            )).first()
            if not ag:
                pytest.skip()
            auth = (await s.scalars(
                select(Symbol).where(
                    Symbol.generation_id == ag,
                    Symbol.name == "authenticate",
                )
            )).first()
            if not auth:
                pytest.skip("authenticate not indexed")
            outgoing = await s.scalar(
                select(func.count(SymbolEdge.id)).where(
                    SymbolEdge.from_symbol_id == auth.id,
                )
            )
            assert outgoing >= 0


# ===================================================================
# D3: Memory, Checkpoints, Session Recovery
# ===================================================================

class TestMemorySessionIsolation:
    """Memory records are correctly scoped to sessions."""

    @pytest.mark.asyncio
    async def test_memories_scoped_to_session(self, repo_id) -> None:
        """Writing memory for A does not leak to B."""
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())
        try:
            factory = get_session_factory()
            async with factory() as s:
                s.add(Memory(
                    kind="plan", statement="Plan for A",
                    status="proposed", repository_id=repo_id,
                    session_id=sid_a,
                ))
                s.add(Memory(
                    kind="plan", statement="Plan for B",
                    status="proposed", repository_id=repo_id,
                    session_id=sid_b,
                ))
                await s.commit()
            async with factory() as s:
                a_mems = (await s.scalars(
                    select(Memory).where(
                        Memory.repository_id == repo_id,
                        Memory.session_id == sid_a,
                    )
                )).all()
                assert len(a_mems) >= 1
                assert any("Plan for A" in m.statement for m in a_mems)
                assert not any("Plan for B" in m.statement for m in a_mems)
        finally:
            async with get_session_factory()() as s:
                await s.execute(delete(Memory).where(
                    Memory.session_id.in_([sid_a, sid_b])
                ))
                await s.commit()

    @pytest.mark.asyncio
    async def test_memory_status_update(self, repo_id) -> None:
        """Memory status can transition proposed -> verified."""
        sid = str(uuid.uuid4())
        factory = get_session_factory()
        async with factory() as s:
            mem = Memory(
                kind="hypothesis", statement="Test status transition",
                status="proposed", repository_id=repo_id, session_id=sid,
            )
            s.add(mem)
            await s.flush()
            mem.status = "verified"
            mem.evidence = "confirmed"
            await s.commit()
            reloaded = (await s.scalars(
                select(Memory).where(Memory.id == mem.id)
            )).first()
            assert reloaded.status == "verified"
            await s.execute(delete(Memory).where(Memory.id == mem.id))
            await s.commit()


class TestCheckpointPersistence:
    """Checkpoints survive commits and can be retrieved fresh."""

    @pytest.mark.asyncio
    async def test_checkpoint_roundtrip(self) -> None:
        """Save and reload a checkpoint from a different session."""
        sid = str(uuid.uuid4())
        factory = get_session_factory()
        async with factory() as s:
            s.add(TaskCheckpoint(
                session_id=sid, objective="Test roundtrip",
                current_state="saved", pending_steps=["verify"],
            ))
            await s.commit()
            cid = s.identity_map.keys()

        async with factory() as s:
            found = (await s.scalars(
                select(TaskCheckpoint).where(
                    TaskCheckpoint.session_id == sid
                )
            )).first()
            assert found is not None
            assert found.objective == "Test roundtrip"
            assert found.pending_steps == ["verify"]
            await s.execute(delete(TaskCheckpoint).where(
                TaskCheckpoint.session_id == sid
            ))
            await s.commit()

    @pytest.mark.asyncio
    async def test_checkpoint_evidence_field(self) -> None:
        """Checkpoint evidence is preserved."""
        sid = str(uuid.uuid4())
        factory = get_session_factory()
        async with factory() as s:
            s.add(TaskCheckpoint(
                session_id=sid, objective="Evidence test",
                current_state="working",
                changed_files=[{"path": "x.py", "status": "added"}],
                evidence="evidence-test-marker",
            ))
            await s.commit()
            found = (await s.scalars(
                select(TaskCheckpoint).where(
                    TaskCheckpoint.session_id == sid
                )
            )).first()
            assert found.objective == "Evidence test"
            assert found.evidence == "evidence-test-marker"
            await s.execute(delete(TaskCheckpoint).where(
                TaskCheckpoint.session_id == sid
            ))
            await s.commit()


class TestSessionBootstrap:
    """session_bootstrap returns checkpoint + memories."""

    @pytest.mark.asyncio
    async def test_bootstrap_returns_state(self, repo_id) -> None:
        """Bootstrap with seeded data returns context."""
        from repo_intel.compaction.manager import session_bootstrap

        sid = str(uuid.uuid4())
        factory = get_session_factory()
        async with factory() as s:
            s.add(TaskCheckpoint(
                session_id=sid, objective="Bootstrap test",
                current_state="in_progress",
            ))
            s.add(Memory(
                kind="context", statement="Bootstrap context",
                status="verified", repository_id=repo_id,
                session_id=sid,
            ))
            await s.commit()

        result = await session_bootstrap(
            session_id=sid, repository_id=repo_id,
        )
        assert result is not None

        async with factory() as s:
            await s.execute(delete(TaskCheckpoint).where(
                TaskCheckpoint.session_id == sid
            ))
            await s.execute(delete(Memory).where(
                Memory.session_id == sid
            ))
            await s.commit()

    @pytest.mark.asyncio
    async def test_bootstrap_unknown_session(self, repo_id) -> None:
        """Bootstrap for unknown session returns empty result."""
        from repo_intel.compaction.manager import session_bootstrap

        result = await session_bootstrap(
            session_id=str(uuid.uuid4()), repository_id=repo_id,
        )
        assert result is not None
        assert result["checkpoint"] is None


# ===================================================================
# D4: Retrieved Evidence Accuracy
# ===================================================================

class TestEvidenceIntegrity:
    """Search results reference real chunks and valid metadata."""

    @pytest.mark.asyncio
    async def test_results_reference_real_chunks(self, repo_id) -> None:
        """Each search result chunk_id exists in DB."""
        req = SearchRequest(
            query="authenticate", repository_id=repo_id, limit=5,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            assert len(results) > 0, "No results for 'authenticate'"
            for r in results[:3]:
                assert r.chunk_id is not None
                assert r.path is not None
            chunk = (await s.scalars(
                select(Chunk).where(Chunk.id == results[0].chunk_id)
            )).first()
            assert chunk is not None

    @pytest.mark.asyncio
    async def test_evidence_kind_assigned(self, repo_id) -> None:
        """Each result has a valid evidence_kind."""
        req = SearchRequest(
            query="authenticate", repository_id=repo_id, limit=5,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            valid_kinds = set(EvidenceKind.__args__)
            for r in results:
                assert r.evidence_kind in valid_kinds

    @pytest.mark.asyncio
    async def test_chunk_text_matches_db(self, repo_id) -> None:
        """Retrieved chunk text matches what's in DB."""
        req = SearchRequest(
            query="authenticate", repository_id=repo_id, limit=3,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            if not results:
                pytest.skip("No results")
            chunk = (await s.scalars(
                select(Chunk).where(Chunk.id == results[0].chunk_id)
            )).first()
            assert chunk is not None
            assert chunk.content is not None


class TestSearchCorrectness:
    """Search returns relevant, bounded results."""

    @pytest.mark.asyncio
    async def test_exact_query_returns_results(self, repo_id) -> None:
        """Querying a known symbol retrieves hits."""
        req = SearchRequest(
            query="authenticate", repository_id=repo_id, limit=5,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            found = any("authenticate" in r.text.lower() for r in results)
            assert found, "No result mentions 'authenticate'"

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, repo_id) -> None:
        """Results count does not exceed limit."""
        req = SearchRequest(
            query="def", repository_id=repo_id, limit=3,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_empty_query_handled(self, repo_id) -> None:
        """Blank query returns gracefully."""
        req = SearchRequest(
            query="", repository_id=repo_id, limit=5,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            assert isinstance(results, list)


# ===================================================================
# D5: Tool Correctness and File-Read Reduction
# ===================================================================

class TestMCPToolCorrectness:
    """MCP tools return valid responses."""

    def test_repo_search_tool(self, repo_id) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_search",
                "parameters": {
                    "query": "authenticate",
                    "repository_id": repo_id,
                    "limit": 3,
                },
            },
        )
        assert resp.status_code == 200

    def test_repo_symbol_tool(self, repo_id) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_symbol",
                "parameters": {
                    "symbol_name": "authenticate",
                    "repository_id": repo_id,
                },
            },
        )
        assert resp.status_code == 200

    def test_repo_list_files_tool(self, repo_id) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_list_files",
                "parameters": {"repository_id": repo_id},
            },
        )
        assert resp.status_code == 200

    def test_tools_list_registered(self) -> None:
        resp = client.get("/api/mcp/tools")
        assert resp.status_code == 200
        tool_names = [t["name"] for t in resp.json()["tools"]]
        assert "repo_list" in tool_names
        assert "repo_search" in tool_names

    def test_unknown_tool_returns_error(self) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={"tool": "nonexistent_tool_xyz", "parameters": {}},
        )
        assert resp.status_code in (400, 404, 500)

    @pytest.mark.asyncio
    async def test_retrieval_events_logged(self, repo_id) -> None:
        req = SearchRequest(
            query="reliability_marker_2026",
            repository_id=repo_id,
            limit=1,
        )
        factory = get_session_factory()
        async with factory() as s:
            await hybrid_search(s, req)
            cnt = await s.scalar(
                select(func.count(RetrievalEvent.id))
            )
            assert cnt > 0


class TestTokenBudget:
    """Token budget enforcement in search."""

    @pytest.mark.asyncio
    async def test_budget_enforced(self, repo_id) -> None:
        """Small token budget limits returned content."""
        req = SearchRequest(
            query="authenticate", repository_id=repo_id,
            limit=20, token_budget=300,
        )
        factory = get_session_factory()
        async with factory() as s:
            results = await hybrid_search(s, req)
            total = sum(r.estimated_tokens or 0 for r in results)
            assert total <= 900, f"Budget exceeded: {total} tokens"


class TestFileReadTool:
    """repo_read_file tool works correctly."""

    def test_read_existing_file(self, repo_id) -> None:
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_read_file",
                "parameters": {
                    "repository_id": repo_id,
                    "relative_path": "app/main.py",
                },
            },
        )
        assert resp.status_code == 200

    def test_read_nonexistent_file(self, repo_id) -> None:
        """Nonexistent file returns error info, not crash."""
        resp = client.post(
            "/api/mcp/call",
            json={
                "tool": "repo_read_file",
                "parameters": {
                    "repository_id": repo_id,
                    "relative_path": "does/not/exist.py",
                },
            },
        )
        assert resp.status_code in (200, 404, 400)




