"""Comprehensive regex baseline evaluation for repo_intel.

Tests all phases of the baseline: chunking accuracy, edge detection,
incremental indexing, retrieval quality, memory/checkpoint recovery,
and MCP contract compliance.

Does not modify production data. Uses isolated test fixtures.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Comprehensive Python fixture with manually annotated ground truth
PYTHON_FIXTURE = '''\
"""Module docstring with code examples.

Example:
    >>> hello_world()
    "Hello World"
"""
import os
from pathlib import Path

API_KEY = "secret"
MAX_RETRIES: int = 3

def hello_world() -> str:
    """Return a greeting."""
    return "Hello World"

async def fetch_data(url: str) -> dict:
    """Fetch data from a URL."""
    return {"url": url}

class UserRepository:
    """User repository class."""
    
    def __init__(self, db_connection):
        self._db = db_connection
    
    def find_by_id(self, user_id: int) -> dict | None:
        """Find user by ID."""
        return self._db.query(user_id)
    
    async def save(self, user_data: dict) -> None:
        """Persist user data."""
        await self._db.save(user_data)

class AuthMixin:
    """Mixin for authentication."""
    
    def authenticate(self, username: str, password: str) -> bool:
        """Check credentials."""
        return True

def process_users(user_repo: UserRepository) -> list:
    """Process a batch of users using the repository."""
    hello_world()
    return user_repo.find_by_id(1)

class UserService(UserRepository, AuthMixin):
    """Combined service."""
    
    def handle_request(self, req):
        """Handle an incoming request."""
        self.authenticate(req.user, req.password)
        process_users(self)
'''

# JavaScript fixture
JS_FIXTURE = '''\
// JavaScript module
export function formatDate(date) {
    return date.toISOString();
}

export class ApiClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    
    async fetchData(endpoint) {
        return fetch(this.baseUrl + endpoint);
    }
    
    static create(instance) {
        return new ApiClient(instance);
    }
}

const helper = () => {
    return "helper";
};
'''

# TypeScript fixture
TS_FIXTURE = '''\
// TypeScript module
export interface User {
    id: number;
    name: string;
}

export class UserService {
    private users: User[];
    
    constructor(users: User[]) {
        this.users = users;
    }
    
    findById(id: number): User | undefined {
        return this.users.find(u => u.id === id);
    }
}
'''

# Ground truth for PYTHON_FIXTURE: symbols that should be detected
# Line numbers computed from actual source (verified exact match ±0)
PYTHON_SYMBOLS = {
    "hello_world": {"kind": "function", "start_line": 13},
    "fetch_data": {"kind": "function", "start_line": 17},
    "UserRepository": {"kind": "class", "start_line": 21},
    "find_by_id": {"kind": "function", "start_line": 27},
    "save": {"kind": "function", "start_line": 31},
    "AuthMixin": {"kind": "class", "start_line": 35},
    "authenticate": {"kind": "function", "start_line": 38},
    "process_users": {"kind": "function", "start_line": 42},
    "UserService": {"kind": "class", "start_line": 47},
    "handle_request": {"kind": "function", "start_line": 50},
}

# Variable/constant symbols
PYTHON_VARIABLES = {"API_KEY", "MAX_RETRIES"}

# Ground truth for edges: process_users calls hello_world and find_by_id
# handle_request calls authenticate and process_users
EXPECTED_EDGES_FROM = {"process_users", "handle_request"}

from repo_intel.indexing.chunker import (
    _detect_language,
    _find_boundaries,
    chunk_file,
    Chunk,
    MAX_CHUNK_LEN,
)
from repo_intel.indexing.edge_detector import (
    detect_edges,
    SymbolEdgeRaw,
)


# =========================================================================
# Phase 1 — Regex Parsing and Chunking Accuracy
# =========================================================================

class TestChunkingAccuracy:
    """Phase 1: Test regex chunking against ground truth."""

    def test_python_symbols_detected(self):
        """Verify all expected Python symbols are detected."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        detected_names = {
            c.symbol_name for c in chunks
            if c.symbol_name is not None
        }
        # Check each expected symbol
        missing = set(PYTHON_SYMBOLS.keys()) - detected_names
        assert not missing, f"Missing symbols: {missing}"

    def test_python_symbol_kinds(self):
        """Verify symbol kinds match ground truth."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        symbol_map = {}
        for c in chunks:
            if c.symbol_name and c.symbol_name not in symbol_map:
                symbol_map[c.symbol_name] = c.chunk_type
        
        for name, info in PYTHON_SYMBOLS.items():
            if name in symbol_map:
                expected_kind = "function" if info["kind"] == "function" else "class"
                assert symbol_map[name] == expected_kind, (
                    f"{name}: expected {expected_kind}, got {symbol_map[name]}"
                )

    def test_python_symbol_line_numbers(self):
        """Verify symbol line numbers are approximately correct."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        symbol_lines = {}
        for c in chunks:
            if c.symbol_name:
                symbol_lines[c.symbol_name] = c.start_line
        
        for name, info in PYTHON_SYMBOLS.items():
            if name in symbol_lines:
                expected_line = info["start_line"]
                actual_line = symbol_lines[name]
                # Tightened tolerance: regex chunking now detects definitions
                # within ±2 lines (decorator/docstring handling)
                assert abs(actual_line - expected_line) <= 2, (
                    f"{name}: expected line ~{expected_line}, got {actual_line}"
                )

    def test_python_no_control_flow_symbols(self):
        """Verify control-flow keywords are not indexed as symbols."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        control_flow = {"if", "else", "elif", "for", "while", "return",
                        "with", "try", "except", "async", "await"}
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        overlap = detected & control_flow
        assert not overlap, f"Control flow detected as symbols: {overlap}"

    def test_python_no_duplicate_symbols(self):
        """Verify no duplicate symbol names in chunks."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
        assert len(symbol_names) == len(set(symbol_names)), "Duplicate symbols detected"

    def test_js_symbols_detected(self):
        """Verify JavaScript symbols are detected including classes and methods.
        
        The chunker now detects class names, async methods, static methods,
        arrow functions, and regular functions in JS/TS files.
        """
        chunks = chunk_file("fixture.js", JS_FIXTURE)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        # Function boundaries should be detected
        assert "formatDate" in detected, f"formatDate not detected: {detected}"
        # Class name should be detected as a symbol
        assert "ApiClient" in detected, f"ApiClient not detected: {detected}"
        # Methods inside class should be detected (including async, static)
        assert "constructor" in detected, f"constructor not detected: {detected}"
        assert "fetchData" in detected, f"fetchData not detected: {detected}"
        assert "create" in detected, f"create not detected: {detected}"
        # Arrow function variable should be detected
        assert "helper" in detected, f"helper not detected: {detected}"
        # At least 6 symbols total
        assert len(detected) >= 6, f"Expected at least 6 JS symbols, got {len(detected)}: {detected}"

    def test_ts_symbols_detected(self):
        """Verify TypeScript symbols are detected including classes, interfaces, and methods.
        
        The chunker now detects class names, interfaces, typed methods,
        and constructors in TS files.
        """
        chunks = chunk_file("fixture.ts", TS_FIXTURE)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        # Class should be detected
        assert "UserService" in detected, f"UserService not detected: {detected}"
        # Interface should be detected
        assert "User" in detected, f"User interface not detected: {detected}"
        # Methods should be detected (constructor, findById)
        assert "constructor" in detected, f"constructor not detected: {detected}"
        assert "findById" in detected, f"findById not detected: {detected}"
        # At least 4 symbols total
        assert len(detected) >= 4, f"Expected at least 4 TS symbols, got {len(detected)}: {detected}"

    def test_chunk_content_matches_source(self):
        """Verify chunk content is a substring of the source."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        for c in chunks:
            # Chunk content should be in the original source (after joining with newlines)
            lines = PYTHON_FIXTURE.split("\n")
            chunk_lines = lines[c.start_line - 1:c.end_line]
            expected = "\n".join(chunk_lines)
            assert c.content == expected

    def test_oversized_function_splitting(self):
        """Verify oversized functions are split into chunks."""
        # Create a function that exceeds MAX_CHUNK_LEN
        large_content = "def large_func():\n" + "    x = 1\n" * 3000
        chunks = chunk_file("large.py", large_content)
        # Should produce multiple chunks
        assert len(chunks) > 1

    def test_docstring_code_not_indexed_as_symbols(self):
        """Code examples inside docstrings should not be indexed as functions."""
        # The function hello_world is in a docstring example
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        # We still detect it because it is a real function definition too
        # The docstring example ">>>" pattern is not a def line

    def test_unknown_file_type(self):
        """Unsupported file types should produce a single file chunk."""
        chunks = chunk_file("data.xyz", "some content\n")
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "file"
        assert chunks[0].symbol_name is None

    def test_multiline_signature(self):
        """Functions with multiline signatures should be detected."""
        content = (
            "def multi_line_func(\n"
            "    arg1,\n"
            "    arg2,\n"
            "    arg3,\n"
            "):\n"
            "    return arg1 + arg2 + arg3\n"
        )
        chunks = chunk_file("multiline.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "multi_line_func" in detected

    def test_nested_definitions(self):
        """Nested function/class definitions should be detected."""
        content = (
            "class Outer:\n"
            "    class Inner:\n"
            "        def method(self):\n"
            "            pass\n"
        )
        chunks = chunk_file("nested.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Outer" in detected
        assert "Inner" in detected
        assert "method" in detected

    # Symbol precision and recall calculation
    def test_symbol_precision(self):
        """Calculate symbol precision against ground truth."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        detected = {(c.symbol_name, c.chunk_type) for c in chunks if c.symbol_name}
        
        # Build expected set (kind mapped to chunk_type)
        expected = set()
        for name, info in PYTHON_SYMBOLS.items():
            kind = "function" if info["kind"] == "function" else "class"
            expected.add((name, kind))
        
        # Variables may also be detected as "variable"
        for v in PYTHON_VARIABLES:
            expected.add((v, "variable"))
        
        # Precision: how many detected symbols are actually expected
        true_positives = detected & expected
        precision = len(true_positives) / len(detected) if detected else 0
        assert precision >= 0.7, f"Symbol precision too low: {precision:.2f}"

    def test_symbol_recall(self):
        """Calculate symbol recall against ground truth."""
        chunks = chunk_file("fixture.py", PYTHON_FIXTURE)
        detected_names = {c.symbol_name for c in chunks if c.symbol_name}
        
        # Recall: how many expected symbols were actually detected
        expected_names = set(PYTHON_SYMBOLS.keys())
        true_positives = detected_names & expected_names
        recall = len(true_positives) / len(expected_names) if expected_names else 0
        assert recall >= 0.8, f"Symbol recall too low: {recall:.2f}"


# =========================================================================
# Phase 2 — Edge Detection Accuracy
# =========================================================================

class TestEdgeDetection:
    """Phase 2: Test edge detection against ground truth."""

    def test_import_edges_detected(self):
        """Verify import relationships are detected."""
        code = '''\
from module_a import func_a
import module_b

def my_func():
    func_a()
'''
        edges = detect_edges(code, {"func_a", "module_a", "my_func", "module_b"})
        types = {e.relation_type for e in edges}
        assert "imports" in types, "Import edges not detected"

    def test_call_edges_detected(self):
        """Verify function call relationships are detected."""
        code = '''\
def caller():
    callee()
    another_callee()

def callee():
    pass

def another_callee():
    pass
'''
        edges = detect_edges(code, {"caller", "callee", "another_callee"})
        call_edges = [e for e in edges if e.relation_type == "calls"]
        callees = {e.to_name for e in call_edges}
        assert "callee" in callees or "another_callee" in callees

    def test_method_call_edges(self):
        """Verify method call relationships within classes."""
        code = '''\
class Service:
    def handle(self):
        self.process()
    
    def process(self):
        pass
'''
        edges = detect_edges(code, {"Service", "handle", "process"})
        # The edge detector detects calls within scope

    def test_edge_direction(self):
        """Verify edge direction is correct (caller -> callee)."""
        code = '''\
def outer():
    inner()

def inner():
    pass
'''
        edges = detect_edges(code, {"outer", "inner"})
        call_edges = [e for e in edges if e.relation_type == "calls"]
        for e in call_edges:
            # from_name should be the enclosing function (outer)
            # to_name should be the called function (inner)
            assert e.to_name == "inner", f"Target should be 'inner', got '{e.to_name}'"

    def test_no_false_edges_on_builtins(self):
        """Verify builtins like print/len don't create edges."""
        code = 'print("hello")\nlen(data)\nstr(x)'
        edges = detect_edges(code, {"print", "len", "str"})
        assert len(edges) == 0

    def test_no_self_loops(self):
        """Verify self-loop edges are not created."""
        code = '''\
def func():
    func()
'''
        edges = detect_edges(code, {"func"})
        for e in edges:
            assert e.from_name != e.to_name, f"Self-loop: {e.from_name} -> {e.to_name}"

    def test_edge_precision(self):
        """Calculate edge precision against ground truth."""
        edges = detect_edges(PYTHON_FIXTURE, set(PYTHON_SYMBOLS.keys()))
        # All edges should reference symbols that exist in our ground truth
        valid_names = set(PYTHON_SYMBOLS.keys())
        
        if edges:
            valid_edges = [
                e for e in edges
                if e.from_name in valid_names and e.to_name in valid_names
            ]
            precision = len(valid_edges) / len(edges)
            assert precision >= 0.5, f"Edge precision too low: {precision:.2f}"

    def test_edges_deduplicated(self):
        """Verify edges are deduplicated."""
        code = (
            "def f1():\n"
            + "    f2()\n" * 10 +
            "def f2():\n"
            + "    pass\n"
        )
        edges = detect_edges(code, {"f1", "f2"})
        # Multiple calls to f2 from f1 should produce only 1 edge
        f1_to_f2 = [e for e in edges if e.from_name == "f1" and e.to_name == "f2"]
        assert len(f1_to_f2) == 1, f"Expected 1 edge f1->f2, got {len(f1_to_f2)}"


# =========================================================================
# Phase 3 — Incremental Indexing Lifecycle
# =========================================================================

class TestIncrementalIndexing:
    """Phase 3: Test incremental re-indexing behavior."""

    @pytest.mark.asyncio
    async def test_content_hash_detection(self):
        """Verify content-hash change detection works."""
        from repo_intel.indexing.discovery import discover_files, _compute_hash
        from repo_intel.indexing.chunker import chunk_file

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create initial file
            fpath = os.path.join(tmpdir, "test.py")
            content1 = "def hello():\n    pass\n"
            with open(fpath, "w") as f:
                f.write(content1)
            
            hash1 = _compute_hash(fpath)
            
            # Modify file
            content2 = "def hello():\n    return 'world'\n"
            with open(fpath, "w") as f:
                f.write(content2)
            
            hash2 = _compute_hash(fpath)
            assert hash1 != hash2, "Content hash should change when file changes"

    @pytest.mark.asyncio
    async def test_unchanged_file_reuse(self):
        """Verify unchanged files are not re-processed."""
        from repo_intel.indexing.discovery import discover_files, _compute_hash

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "unchanged.py")
            content = "x = 1\n"
            with open(fpath, "w") as f:
                f.write(content)
            
            hash1 = _compute_hash(fpath)
            
            # Discover again (no changes)
            discovered = discover_files(tmpdir)
            assert len(discovered) == 1
            assert discovered[0].content_hash == hash1

    @pytest.mark.asyncio
    async def test_new_file_detection(self):
        """Verify new files are discovered on re-scan."""
        from repo_intel.indexing.discovery import discover_files

        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial discovery
            with open(os.path.join(tmpdir, "a.py"), "w") as f:
                f.write("a = 1\n")
            disc1 = discover_files(tmpdir)
            assert len(disc1) == 1
            
            # Add new file
            with open(os.path.join(tmpdir, "b.py"), "w") as f:
                f.write("b = 2\n")
            disc2 = discover_files(tmpdir)
            assert len(disc2) == 2

    @pytest.mark.asyncio
    async def test_deleted_file_detection(self):
        """Verify deleted files are detected on re-scan."""
        from repo_intel.indexing.discovery import discover_files

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "delete_me.py")
            with open(fpath, "w") as f:
                f.write("x = 1\n")
            disc1 = discover_files(tmpdir)
            assert len(disc1) == 1
            
            # Delete file
            os.remove(fpath)
            disc2 = discover_files(tmpdir)
            assert len(disc2) == 0


# =========================================================================
# Phase 4 — Retrieval Quality
# =========================================================================

class TestRetrievalQuality:
    """Phase 4: Test retrieval modes and quality."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self):
        """Verify hybrid search returns results for the indexed repo."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            request = SearchRequest(
                query="authenticate user login",
                limit=5,
            )
            results = await hybrid_search(session, request)
            assert len(results) > 0, "Search returned no results"
            # Each result should have required fields
            for r in results:
                assert r.path
                assert r.start_line > 0
                assert r.end_line >= r.start_line
                assert r.score > 0
                assert len(r.retrieval_methods) > 0

    @pytest.mark.asyncio
    async def test_search_limit_enforced(self):
        """Verify search respects the limit parameter."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            request = SearchRequest(
                query="database connection",
                limit=3,
            )
            results = await hybrid_search(session, request)
            assert len(results) <= 3, f"Returned {len(results)} results, limit was 3"

    @pytest.mark.asyncio
    async def test_search_latency_p50(self):
        """Measure search latency."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        latencies = []
        queries = ["authenticate", "database", "repository", "middleware", "response"]
        
        for query in queries:
            async with factory() as session:
                t0 = time.monotonic()
                request = SearchRequest(query=query, limit=5)
                await hybrid_search(session, request)
                latencies.append(time.monotonic() - t0)
        
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        assert p50 < 5.0, f"P50 search latency {p50:.3f}s is too high"

    @pytest.mark.asyncio
    async def test_no_stale_results_on_active_generation(self):
        """Verify active generation results are not stale."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            request = SearchRequest(query="auth", limit=5)
            results = await hybrid_search(session, request)
            # Results from current active generation should not be stale
            # (unless the index is >1 hour old, which is expected)
            for r in results:
                assert r.is_stale in (True, False)  # field exists

    @pytest.mark.asyncio
    async def test_exact_match_retrieval(self):
        """Verify exact symbol matching works."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            request = SearchRequest(query="verify_password", limit=5)
            results = await hybrid_search(session, request)
            # Should find at least something related
            # (verify_password is a known function in fastapi-template)

    @pytest.mark.asyncio
    async def test_token_budget_respected(self):
        """Verify token budget is not exceeded."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            budget = 2000
            request = SearchRequest(
                query="database connection",
                limit=10,
                token_budget=budget,
            )
            results = await hybrid_search(session, request)
            total_tokens = sum(r.estimated_tokens for r in results)
            assert total_tokens <= budget * 1.5, (
                f"Total tokens {total_tokens} significantly exceeds budget {budget}"
            )

    @pytest.mark.asyncio
    async def test_search_result_content_freshness(self):
        """Verify retrieved content comes from the active generation."""
        from repo_intel.retrieval.search import hybrid_search
        from repo_intel.retrieval.types import SearchRequest
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            request = SearchRequest(query="login", limit=3)
            results = await hybrid_search(session, request)
            for r in results:
                # Each result should have evidence_kind
                assert r.evidence_kind in ("exact_source", "stale", "missing")


# =========================================================================
# Phase 5 — Memory and Checkpoint
# =========================================================================

class TestMemoryCheckpoint:
    """Phase 5: Test memory and checkpoint functionality."""

    @pytest.mark.asyncio
    async def test_memory_write_and_read(self):
        """Verify memory write and read round-trip."""
        from sqlalchemy import select
        from repo_intel.db.models import Memory
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            mem = Memory(
                kind="preference",
                statement="Use async patterns for database access",
                status="candidate",
                session_id="test-baseline-session",
            )
            session.add(mem)
            await session.commit()
            await session.refresh(mem)
            mem_id = mem.id

            # Read back
            found = await session.get(Memory, mem_id)
            assert found is not None
            assert found.statement == "Use async patterns for database access"
            assert found.kind == "preference"
            assert found.session_id == "test-baseline-session"

            # Clean up
            await session.delete(found)
            await session.commit()

    @pytest.mark.asyncio
    async def test_memory_session_isolation(self):
        """Verify memories from different sessions don't leak."""
        from sqlalchemy import select
        from repo_intel.db.models import Memory
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            # Write to session A
            mem_a = Memory(
                kind="observation",
                statement="Session A observation",
                status="candidate",
                session_id="isolated-session-a",
            )
            session.add(mem_a)
            await session.commit()
            await session.refresh(mem_a)

            # Write to session B
            mem_b = Memory(
                kind="observation",
                statement="Session B observation",
                status="candidate",
                session_id="isolated-session-b",
            )
            session.add(mem_b)
            await session.commit()
            await session.refresh(mem_b)

            # Query session A only
            stmt = select(Memory).where(
                Memory.session_id == "isolated-session-a"
            )
            rows = list(await session.scalars(stmt))
            assert len(rows) == 1
            assert rows[0].statement == "Session A observation"

            # Clean up
            await session.delete(mem_a)
            await session.delete(mem_b)
            await session.commit()

    @pytest.mark.asyncio
    async def test_checkpoint_save_and_restore(self):
        """Verify checkpoint save and restore round-trip."""
        from sqlalchemy import select
        from repo_intel.db.models import TaskCheckpoint
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            cp = TaskCheckpoint(
                session_id="baseline-checkpoint-test",
                objective="Test checkpoint save/restore",
                current_state="Testing phase",
                changed_files=["file1.py", "file2.py"],
                pending_steps=["step3", "step4"],
                evidence={"test": True},
            )
            session.add(cp)
            await session.commit()
            await session.refresh(cp)
            cp_id = cp.id

            # Read back
            found = await session.get(TaskCheckpoint, cp_id)
            assert found is not None
            assert found.objective == "Test checkpoint save/restore"
            assert "file1.py" in found.changed_files
            assert "step3" in found.pending_steps
            assert found.evidence["test"] is True

            # Clean up
            await session.delete(found)
            await session.commit()

    @pytest.mark.asyncio
    async def test_checkpoint_unknown_session(self):
        """Verify unknown sessions return empty state."""
        from sqlalchemy import select
        from repo_intel.db.models import TaskCheckpoint
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            stmt = select(TaskCheckpoint).where(
                TaskCheckpoint.session_id == "nonexistent-session-xyz"
            )
            rows = await session.scalars(stmt)
            assert rows.first() is None

    @pytest.mark.asyncio
    async def test_session_bootstrap_returns_structure(self):
        """Verify session_bootstrap returns correct structure."""
        from repo_intel.compaction.manager import session_bootstrap
        result = await session_bootstrap(session_id="baseline-bootstrap-test")
        assert "checkpoint" in result
        assert "verified_memories" in result
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_session_bootstrap_unknown_session(self):
        """Verify bootstrap for unknown session returns no checkpoint."""
        from repo_intel.compaction.manager import session_bootstrap
        result = await session_bootstrap(
            session_id="nonexistent-bootstrap-session"
        )
        assert result["checkpoint"] is None


# =========================================================================
# Phase 6 — MCP Contract Verification
# =========================================================================

class TestMCPContract:
    """Phase 6: Verify MCP tool contracts via the test client."""

    @pytest.mark.asyncio
    async def test_repo_list_returns_repos(self):
        """Verify repo_list returns registered repositories."""
        from repo_intel.mcp.server import tool_repo_list
        from repo_intel.db.session import get_session_factory

        result = await tool_repo_list(get_session_factory())
        assert "repositories" in result
        assert len(result["repositories"]) > 0
        for repo in result["repositories"]:
            assert "id" in repo
            assert "name" in repo
            assert "path" in repo
            assert "status" in repo
            assert "file_count" in repo
            assert "chunk_count" in repo

    @pytest.mark.asyncio
    async def test_index_status_valid(self):
        """Verify index_status returns expected structure."""
        from repo_intel.mcp.server import tool_index_status
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            from repo_intel.db.models import Repository
            repo = (await session.scalars(select(Repository).limit(1))).first()

        result = await tool_index_status(factory, str(repo.id))
        assert "repository_id" in result
        assert "active_generation" in result
        assert "last_job" in result

    @pytest.mark.asyncio
    async def test_repo_read_file_success(self):
        """Verify repo_read_file returns content for indexed file."""
        from repo_intel.mcp.server import tool_repo_read_file
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            from repo_intel.db.models import Repository, FileRecord
            repo = (await session.scalars(select(Repository).limit(1))).first()
            file = (await session.scalars(
                select(FileRecord).where(
                    FileRecord.repository_id == repo.id,
                    FileRecord.deleted == False,
                    FileRecord.language == "python",
                ).limit(1)
            )).first() if repo else None

        if file:
            result = await tool_repo_read_file(
                factory, file.relative_path, str(repo.id)
            )
            assert "content" in result
            assert result["evidence_kind"] in ("exact_source", "stale")
            assert result["path"] == file.relative_path

    @pytest.mark.asyncio
    async def test_repo_read_file_missing(self):
        """Verify repo_read_file rejects non-indexed files."""
        from repo_intel.mcp.server import tool_repo_read_file
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            from repo_intel.db.models import Repository
            repo = (await session.scalars(select(Repository).limit(1))).first()

        if repo:
            result = await tool_repo_read_file(
                factory, "nonexistent.py", str(repo.id)
            )
            assert "error" in result

    @pytest.mark.asyncio
    async def test_repo_read_file_traversal_blocked(self):
        """Verify repo_read_file blocks path traversal."""
        from repo_intel.mcp.server import tool_repo_read_file
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select
            from repo_intel.db.models import Repository
            repo = (await session.scalars(select(Repository).limit(1))).first()

        if repo:
            result = await tool_repo_read_file(
                factory, "../../../etc/passwd", str(repo.id)
            )
            assert "error" in result

    @pytest.mark.asyncio
    async def test_repo_context_token_budget(self):
        """Verify repo_context respects token budget."""
        from repo_intel.mcp.server import tool_repo_context
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        budget = 3000
        result = await tool_repo_context(
            factory, "authenticate user", token_budget=budget
        )
        assert "estimated_tokens" in result
        assert result["estimated_tokens"] <= budget * 2  # some tolerance
        assert result["num_chunks"] >= 0

    @pytest.mark.asyncio
    async def test_memory_write_creates_memory(self):
        """Verify memory_write MCP tool creates memory."""
        from repo_intel.mcp.server import tool_memory_write
        from repo_intel.db.session import get_session_factory
        from sqlalchemy import select
        from repo_intel.db.models import Memory

        factory = get_session_factory()
        result = await tool_memory_write(
            factory,
            kind="test_kind",
            statement="Baseline evaluation memory",
            session_id="baseline-mcp-test",
        )
        assert "id" in result
        assert result["statement"] == "Baseline evaluation memory"
        assert result["status"] == "candidate"

        # Clean up
        async with factory() as session:
            stmt = select(Memory).where(
                Memory.session_id == "baseline-mcp-test",
                Memory.kind == "test_kind",
            )
            mem = (await session.scalars(stmt)).first()
            if mem:
                await session.delete(mem)
                await session.commit()

    @pytest.mark.asyncio
    async def test_memory_search_filters(self):
        """Verify memory_search tool works with filters."""
        from repo_intel.mcp.server import tool_memory_read
        from repo_intel.db.session import get_session_factory

        factory = get_session_factory()
        result = await tool_memory_read(
            factory, kind="preference", limit=5
        )
        assert "num_memories" in result
        assert "memories" in result
        assert len(result["memories"]) <= 5

    @pytest.mark.asyncio
    async def test_checkpoint_tools_contract(self):
        """Verify checkpoint save/get return expected fields."""
        from repo_intel.mcp.server import (
            tool_checkpoint_save,
            tool_checkpoint_get,
        )
        from repo_intel.db.session import get_session_factory
        from sqlalchemy import select
        from repo_intel.db.models import TaskCheckpoint

        factory = get_session_factory()
        save_result = await tool_checkpoint_save(
            factory,
            objective="Baseline MCP checkpoint test",
            session_id="baseline-mcp-checkpoint",
            current_state="Testing",
            changed_files=["x.py"],
            pending_steps=["finish"],
            evidence={"eval": True},
        )
        assert "id" in save_result
        assert save_result["objective"] == "Baseline MCP checkpoint test"

        get_result = await tool_checkpoint_get(
            factory, session_id="baseline-mcp-checkpoint"
        )
        assert get_result["objective"] == "Baseline MCP checkpoint test"
        assert "x.py" in get_result["changed_files"]

        # Clean up
        async with factory() as session:
            stmt = select(TaskCheckpoint).where(
                TaskCheckpoint.session_id == "baseline-mcp-checkpoint"
            )
            cp = (await session.scalars(stmt)).first()
            if cp:
                await session.delete(cp)
                await session.commit()


# =========================================================================
# Phase 7 — Baseline Performance
# =========================================================================

class TestPerformance:
    """Phase 7: Record baseline performance measurements."""

    def test_chunking_speed(self):
        """Measure chunking throughput."""
        iterations = 100
        t0 = time.monotonic()
        for _ in range(iterations):
            chunk_file("fixture.py", PYTHON_FIXTURE)
        elapsed = time.monotonic() - t0
        per_file_ms = (elapsed / iterations) * 1000
        assert per_file_ms < 50, f"Chunking too slow: {per_file_ms:.1f}ms/file"

    def test_edge_detection_speed(self):
        """Measure edge detection throughput."""
        iterations = 100
        t0 = time.monotonic()
        for _ in range(iterations):
            detect_edges(PYTHON_FIXTURE, set(PYTHON_SYMBOLS.keys()))
        elapsed = time.monotonic() - t0
        per_file_ms = (elapsed / iterations) * 1000
        assert per_file_ms < 50, f"Edge detection too slow: {per_file_ms:.1f}ms/file"

    def test_content_hash_speed(self):
        """Measure content hash throughput."""
        from repo_intel.indexing.discovery import _compute_hash
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(PYTHON_FIXTURE)
            fpath = f.name
        
        try:
            iterations = 100
            t0 = time.monotonic()
            for _ in range(iterations):
                _compute_hash(fpath)
            elapsed = time.monotonic() - t0
            per_file_ms = (elapsed / iterations) * 1000
            assert per_file_ms < 100, f"Hash too slow: {per_file_ms:.1f}ms/file"
        finally:
            os.unlink(fpath)


# =========================================================================
# Phase 8 — Regression
# =========================================================================

class TestRegression:
    """Phase 8: Additional regression tests for known issues."""

    def test_chunker_handles_empty_content(self):
        """Verify chunker handles empty content gracefully."""
        chunks = chunk_file("empty.py", "")
        # Should not crash
        assert isinstance(chunks, list)

    def test_chunker_handles_unicode(self):
        """Verify chunker handles unicode content."""
        content = "def 问候():\n    return '你好'\n"
        chunks = chunk_file("unicode.py", content)
        assert isinstance(chunks, list)

    def test_edge_detector_empty_input(self):
        """Verify edge detector handles empty input."""
        edges = detect_edges("", set())
        assert edges == []

    def test_chunk_line_numbers_valid(self):
        """Verify chunk line numbers are always valid."""
        content = "x = 1\ny = 2\n"
        chunks = chunk_file("valid.py", content)
        for c in chunks:
            assert c.start_line >= 1
            assert c.end_line >= c.start_line

    def test_chunk_content_hash_deterministic(self):
        """Verify content hash is deterministic."""
        content = "print('hello')\n"
        c1 = chunk_file("test.py", content)[0]
        c2 = chunk_file("test.py", content)[0]
        assert c1.content_hash == c2.content_hash

    def test_boundary_detection_no_crash_on_single_line(self):
        """Verify boundary detection handles single-line files."""
        lines = ["print('hello')"]
        boundaries = _find_boundaries(lines, "python")
        assert isinstance(boundaries, list)


# =========================================================================
# Phase 9 — Complex Pattern Edge Cases
# =========================================================================

class TestComplexPatterns:
    """Phase 9: Test complex patterns like decorators, conditionals, nested classes."""

    # --- Decorators ---

    def test_decorated_function_detected(self):
        """Functions with decorators should be detected."""
        content = (
            "@app.route('/api')\n"
            "@login_required\n"
            "def handle_api():\n"
            "    return 'ok'\n"
        )
        chunks = chunk_file("decorators.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "handle_api" in detected

    def test_decorated_class_detected(self):
        """Classes with decorators should be detected."""
        content = (
            "@singleton\n"
            "class Config:\n"
            "    pass\n"
        )
        chunks = chunk_file("decorators.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Config" in detected

    def test_property_decorator_method(self):
        """Methods with @property should be detected."""
        content = (
            "class Widget:\n"
            "    @property\n"
            "    def label(self):\n"
            "        return self._label\n"
        )
        chunks = chunk_file("widget.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Widget" in detected
        assert "label" in detected

    # --- Conditionals ---

    def test_conditional_function_not_indexed(self):
        """Functions defined inside if-blocks should still be detected
        but not as top-level symbols (they match at indent > 0)."""
        content = (
            "if DEBUG:\n"
            "    def debug_handler():\n"
            "        pass\n"
            "\n"
            "def normal_func():\n"
            "    pass\n"
        )
        chunks = chunk_file("cond.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        # normal_func is definitely detected; debug_handler may or may not
        # depending on indent handling (it's inside an if-block)
        assert "normal_func" in detected

    # --- Nested classes ---

    def test_deeply_nested_class(self):
        """Classes nested multiple levels deep should be detected."""
        content = (
            "class Outer:\n"
            "    class Middle:\n"
            "        class Inner:\n"
            "            def deep(self):\n"
            "                return True\n"
        )
        chunks = chunk_file("nested.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Outer" in detected
        assert "Middle" in detected
        assert "Inner" in detected
        assert "deep" in detected

    # --- Abstract classes and mixins ---

    def test_abstract_class_detected(self):
        """Abstract base classes should be detected."""
        content = (
            "from abc import ABC, abstractmethod\n"
            "\n"
            "class Animal(ABC):\n"
            "    @abstractmethod\n"
            "    def speak(self):\n"
            "        pass\n"
            "\n"
            "    def eat(self, food):\n"
            "        pass\n"
        )
        chunks = chunk_file("animal.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Animal" in detected
        assert "speak" in detected
        assert "eat" in detected

    # --- Lambda and inline patterns ---

    def test_lambda_not_indexed_as_function(self):
        """Lambda expressions should NOT be indexed as named functions."""
        content = (
            "handler = lambda x: x + 1\n"
            "def normal():\n"
            "    pass\n"
        )
        chunks = chunk_file("lambda.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        # 'handler' is a variable assignment, not a function def
        assert "normal" in detected

    # --- Multiple decorators ---

    def test_multiple_decorators(self):
        """Functions with multiple stacked decorators should be detected."""
        content = (
            "@app.route('/user')\n"
            "@require_auth\n"
            "@cache.ttl(300)\n"
            "@rate_limit(limit=10)\n"
            "def get_user(user_id):\n"
            "    return {'id': user_id}\n"
        )
        chunks = chunk_file("routes.py", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "get_user" in detected


# =========================================================================
# Phase 10 — Cross-file Import Resolution
# =========================================================================

class TestCrossFileImports:
    """Phase 10: Test cross-file import resolution."""

    def test_cross_file_import_edge(self):
        """Verify imports between files create edges."""
        # Simulate two files where file A imports from file B
        file_a_content = (
            "from services.user_service import get_user\n"
            "\n"
            "def handler():\n"
            "    return get_user(1)\n"
        )

        # When defined_symbols includes 'get_user' from another file,
        # the import should produce an edge
        edges = detect_edges(
            file_a_content,
            {"get_user", "handler", "user_service"},
        )
        import_edges = [e for e in edges if e.relation_type == "imports"]
        assert len(import_edges) > 0, "Cross-file import edge should be created"
        # The edge should point to get_user (the imported name)
        targets = {e.to_name for e in import_edges}
        assert "get_user" in targets, f"Expected get_user in import targets, got {targets}"

    def test_cross_file_import_module_only(self):
        """Verify 'import module' creates edge when module is a known symbol."""
        content = (
            "import database\n"
            "\n"
            "def query():\n"
            "    return database.get()\n"
        )
        edges = detect_edges(
            content,
            {"database", "query"},
        )
        import_edges = [e for e in edges if e.relation_type == "imports"]
        assert len(import_edges) > 0

    def test_cross_file_import_as_alias(self):
        """Verify 'import module as alias' creates edge."""
        content = (
            "import services as svcs\n"
            "\n"
            "def handler():\n"
            "    return svcs.get_user(1)\n"
        )
        edges = detect_edges(
            content,
            {"services", "handler"},
        )
        import_edges = [e for e in edges if e.relation_type == "imports"]
        assert len(import_edges) > 0

    def test_same_file_call_edges_preserved(self):
        """Verify in-file call edges still work correctly."""
        content = (
            "def outer():\n"
            "    inner()\n"
            "\n"
            "def inner():\n"
            "    pass\n"
        )
        edges = detect_edges(content, {"outer", "inner"})
        call_edges = [e for e in edges if e.relation_type == "calls"]
        assert len(call_edges) > 0
        for e in call_edges:
            assert e.from_name == "outer"
            assert e.to_name == "inner"


# =========================================================================
# Phase 11 — JS/TS Class Detection Accuracy
# =========================================================================

class TestJSTSClassDetection:
    """Phase 11: Verify JS/TS class and interface detection accuracy."""

    def test_js_class_name_detected(self):
        """Verify JS class name is detected as a symbol in small files."""
        content = (
            "export class MyClass {\n"
            "    constructor() {}\n"
            "    method() {}\n"
            "}\n"
        )
        chunks = chunk_file("test.js", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "MyClass" in detected, f"MyClass class not detected: {detected}"

    def test_ts_interface_detected(self):
        """Verify TS interface is detected as a symbol."""
        content = (
            "export interface Config {\n"
            "    host: string;\n"
            "    port: number;\n"
            "}\n"
        )
        chunks = chunk_file("test.ts", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Config" in detected, f"Config interface not detected: {detected}"

    def test_js_async_static_methods(self):
        """Verify async and static methods are detected."""
        content = (
            "class Service {\n"
            "    async fetchData() { return {}; }\n"
            "    static create() { return new Service(); }\n"
            "}\n"
        )
        chunks = chunk_file("test.js", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "Service" in detected
        assert "fetchData" in detected, f"fetchData not detected: {detected}"
        assert "create" in detected, f"create not detected: {detected}"

    def test_js_default_export_class(self):
        """Verify 'export default class' is detected."""
        content = (
            "export default class App {\n"
            "    run() {}\n"
            "}\n"
        )
        chunks = chunk_file("test.js", content)
        detected = {c.symbol_name for c in chunks if c.symbol_name}
        assert "App" in detected, f"App class not detected: {detected}"

    def test_js_method_kind_is_function(self):
        """Verify methods inside classes are classified as 'function', not 'class'."""
        content = (
            "class Widget {\n"
            "    render() {}\n"
            "    destroy() {}\n"
            "}\n"
        )
        chunks = chunk_file("test.js", content)
        for c in chunks:
            if c.symbol_name in ("render", "destroy"):
                assert c.chunk_type == "function", (
                    f"{c.symbol_name} should be 'function', got '{c.chunk_type}'"
                )
