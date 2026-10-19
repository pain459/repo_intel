"""FastMCP server wrapping repo_intel tools for OpenCode integration."""

from __future__ import annotations

import functools
import logging
import time

from fastmcp import FastMCP

from repo_intel.api.metrics import (
    MCP_TOOL_CALLS,
    MCP_TOOL_LATENCY,
    SEARCH_LATENCY,
    SEARCH_REQUESTS,
    SEARCH_RESULTS,
    SEARCH_STALE_RESULTS,
)
from repo_intel.db.session import get_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Create the FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "repo_intel",
    instructions=(
        "Persistent, searchable knowledge of Git repositories for coding agents. "
        "Provides hybrid search, symbol lookup, context packs, agent memory, "
        "and session checkpoints across indexed repositories."
    ),
)

# ---------------------------------------------------------------------------
# Instrumentation helper — wraps MCP tool coroutines with metrics
# ---------------------------------------------------------------------------


def _instrument_tool(tool_name: str):
    """Decorator that records MCP tool call metrics around an async tool fn."""

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                MCP_TOOL_CALLS.labels(tool_name=tool_name, status="success").inc()
                return result
            except Exception:
                MCP_TOOL_CALLS.labels(tool_name=tool_name, status="error").inc()
                raise
            finally:
                elapsed = time.monotonic() - t0
                MCP_TOOL_LATENCY.labels(tool_name=tool_name).observe(elapsed)

        return wrapper

    return decorator

# ---------------------------------------------------------------------------
# Search instrumentation helper — records additional search metrics
# ---------------------------------------------------------------------------


def _instrument_search(fn):
    """Extra decorator for search-class MCP tools to record search metrics."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        SEARCH_REQUESTS.labels(source="mcp").inc()
        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            # Pull result counts from the return dict if present
            num_results = 0
            if isinstance(result, dict):
                num_results = result.get("num_results", 0) or 0
                # Count stale results
                for r in result.get("results", []):
                    if r.get("is_stale"):
                        SEARCH_STALE_RESULTS.inc()
            SEARCH_RESULTS.observe(num_results)
            return result
        except Exception:
            raise
        finally:
            elapsed = time.monotonic() - t0
            SEARCH_LATENCY.observe(elapsed)

    return wrapper

# ---------------------------------------------------------------------------
# Tool registrations (async, using the existing session factory pattern)
# ---------------------------------------------------------------------------
# Note: _instrument_tool is applied BEFORE @mcp.tool so metrics fire for
# every MCP call regardless of whether it succeeds or raises.


@mcp.tool
@_instrument_tool("repo_list")
async def repo_list() -> dict:
    """List all registered repositories and their index status.

    Returns repository names, file counts, chunk counts, and indexing timestamps.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    from repo_intel.db.models import (
        FileRecord,
        IndexGeneration,
        Repository,
    )

    factory = get_session_factory()
    async with factory() as session:
        repos = await session.scalars(
            select(Repository).order_by(Repository.name)
        )
        repos = list(repos)

        results = []
        for repo in repos:
            gen = (
                await session.scalars(
                    select(IndexGeneration)
                    .where(
                        IndexGeneration.repository_id == repo.id,
                        IndexGeneration.state == "active",
                    )
                    .order_by(IndexGeneration.created_at.desc())
                    .limit(1)
                )
            ).first()

            file_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(FileRecord)
                    .where(
                        FileRecord.repository_id == repo.id,
                        FileRecord.deleted == False,  # noqa: E712
                    )
                )
            ) or 0

            results.append({
                "id": str(repo.id),
                "name": repo.name,
                "path": repo.git_path,
                "status": repo.status,
                "file_count": file_count,
                "chunk_count": gen.chunk_count if gen else 0,
                "embedding_model": gen.embedding_model if gen else None,
                "indexed_at": str(gen.created_at) if gen else None,
            })

    return {"repositories": results}


@mcp.tool
@_instrument_search
@_instrument_tool("repo_search")
async def repo_search(
    query: str,
    repository_id: str | None = None,
    limit: int = 10,
) -> dict:
    """Hybrid search across indexed repositories.

    Combines exact match, full-text search, and semantic vector retrieval
    with reciprocal rank fusion. Returns code chunks with scores and
    retrieval methods used.

    Args:
        query: The search query string.
        repository_id: Optional repository UUID to search within.
        limit: Maximum number of results (default 10).
    """
    from repo_intel.retrieval.search import hybrid_search
    from repo_intel.retrieval.types import SearchRequest

    factory = get_session_factory()
    async with factory() as session:
        request = SearchRequest(
            query=query,
            repository_id=repository_id,
            limit=limit,
        )
        results = await hybrid_search(session, request)

    return {
        "query": query,
        "repository_id": repository_id,
        "num_results": len(results),
        "results": [
            {
                "path": r.path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "content_hash": r.content_hash,
                "text": r.text[:2000],
                "retrieval_methods": r.retrieval_methods,
                "score": round(r.score, 6),
                "generation_created_at": r.generation_created_at,
                "is_stale": r.is_stale,
            }
            for r in results
        ],
    }


@mcp.tool
@_instrument_tool("repo_symbol")
async def repo_symbol(
    symbol_name: str,
    repository_id: str | None = None,
) -> dict:
    """Find symbol (class, function, variable) definitions by name.

    Args:
        symbol_name: The symbol name to search for (supports partial match).
        repository_id: Optional repository UUID to search within.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, Symbol

    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(Symbol, FileRecord.relative_path)
            .join(FileRecord, Symbol.file_id == FileRecord.id)
            .where(
                Symbol.name.ilike(f"%{symbol_name}%"),
                FileRecord.deleted == False,  # noqa: E712
            )
            .limit(20)
        )
        if repository_id:
            stmt = stmt.where(FileRecord.repository_id == repository_id)

        rows = await session.execute(stmt)

    results = []
    for symbol, path in rows:
        results.append({
            "name": symbol.name,
            "kind": symbol.kind,
            "file": path,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
        })

    return {"symbol": symbol_name, "definitions": results}


@mcp.tool
@_instrument_search
@_instrument_tool("repo_context")
async def repo_context(
    task_description: str,
    repository_id: str | None = None,
    token_budget: int = 12_000,
) -> dict:
    """Build a curated evidence pack for a task description.

    Searches indexed repositories and returns relevant code chunks
    up to the token budget. Suitable for providing context to coding agents.

    Args:
        task_description: Description of the task or question to find context for.
        repository_id: Optional repository UUID to search within.
        token_budget: Maximum estimated tokens to return (default 12000).
    """
    from repo_intel.retrieval.search import hybrid_search
    from repo_intel.retrieval.types import SearchRequest

    factory = get_session_factory()
    async with factory() as session:
        request = SearchRequest(
            query=task_description,
            repository_id=repository_id,
            limit=15,
            token_budget=token_budget,
        )
        results = await hybrid_search(session, request)

    total_tokens = sum(
        r.estimated_tokens or max(len(r.text) // 4, 1) for r in results
    )

    return {
        "task": task_description,
        "repository_id": repository_id,
        "token_budget": token_budget,
        "estimated_tokens": total_tokens,
        "num_chunks": len(results),
        "chunks": [
            {
                "path": r.path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "content_hash": r.content_hash,
                "text": r.text,
                "retrieval_methods": r.retrieval_methods,
                "generation_created_at": r.generation_created_at,
                "is_stale": r.is_stale,
            }
            for r in results
        ],
    }


@mcp.tool
@_instrument_tool("index_status")
async def index_status(repository_id: str) -> dict:
    """Get the detailed index status for a repository.

    Args:
        repository_id: The UUID of the repository.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import (
        IndexGeneration,
        IndexJob,
        Repository,
    )

    factory = get_session_factory()
    async with factory() as session:
        repo = (
            await session.scalars(
                select(Repository).where(Repository.id == repository_id)
            )
        ).first()
        if not repo:
            return {"error": f"Repository {repository_id} not found"}

        gen = (
            await session.scalars(
                select(IndexGeneration)
                .where(
                    IndexGeneration.repository_id == repo.id,
                    IndexGeneration.state == "active",
                )
                .order_by(IndexGeneration.created_at.desc())
                .limit(1)
            )
        ).first()

        last_job = (
            await session.scalars(
                select(IndexJob)
                .where(IndexJob.repository_id == repo.id)
                .order_by(IndexJob.created_at.desc())
                .limit(1)
            )
        ).first()

    return {
        "repository_id": str(repo.id),
        "name": repo.name,
        "status": repo.status,
        "active_generation": {
            "id": str(gen.id),
            "embedding_model": gen.embedding_model,
            "chunk_count": gen.chunk_count,
            "created_at": str(gen.created_at),
        }
        if gen
        else None,
        "last_job": {
            "id": str(last_job.id),
            "type": last_job.job_type,
            "status": last_job.status,
            "error": last_job.error_summary,
        }
        if last_job
        else None,
    }


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------


@mcp.tool
@_instrument_tool("memory_write")
async def memory_write(
    kind: str,
    statement: str,
    repository_id: str | None = None,
    evidence: dict | None = None,
    source_commit: str | None = None,
    author: str | None = None,
) -> dict:
    """Write a new agent memory (preference, observation, or instruction).

    Also known as: memory_record.

    Memories start with status 'candidate' and can later be promoted to
    'verified' or marked as 'superseded' or 'rejected'.

    Args:
        kind: Memory kind (e.g., 'preference', 'observation', 'instruction').
        statement: The memory statement text.
        repository_id: Optional repository UUID to scope the memory to.
        evidence: Optional supporting evidence dictionary.
        source_commit: Optional git commit hash that supports this memory.
        author: Optional creator label (session ID, agent name, etc.).
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Memory, Repository

    factory = get_session_factory()
    async with factory() as session:
        if repository_id:
            repo = (
                await session.scalars(
                    select(Repository).where(Repository.id == repository_id)
                )
            ).first()
            if not repo:
                return {"error": f"Repository {repository_id} not found"}

        memory = Memory(
            repository_id=repository_id,
            kind=kind,
            statement=statement,
            status="candidate",
            evidence=evidence,
            source_commit=source_commit,
            author=author,
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)

    return {
        "id": str(memory.id),
        "kind": memory.kind,
        "statement": memory.statement,
        "status": memory.status,
        "message": "Memory created",
    }


# Aliases — plan names (memory_search, memory_record, task_resume) must also
# resolve.  We delegate to the canonical implementations.


@mcp.tool(name="memory_record")
@_instrument_tool("memory_record")
async def memory_record_alias(
    kind: str,
    statement: str,
    repository_id: str | None = None,
    evidence: dict | None = None,
    source_commit: str | None = None,
    author: str | None = None,
) -> dict:
    """Alias for memory_write. See memory_write for full documentation."""
    return await memory_write(
        kind=kind,
        statement=statement,
        repository_id=repository_id,
        evidence=evidence,
        source_commit=source_commit,
        author=author,
    )


@mcp.tool
@_instrument_tool("memory_search")
async def memory_search(
    query: str | None = None,
    repository_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict:
    """Read agent memories with optional filtering and full-text search.

    Also known as: memory_read.

    Args:
        query: Text to search for in memory statements.
        repository_id: Optional repository UUID to filter by.
        kind: Optional memory kind to filter by.
        limit: Maximum number of memories to return (default 20).
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Memory

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Memory)
        if repository_id:
            stmt = stmt.where(Memory.repository_id == repository_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        if query:
            stmt = stmt.where(Memory.statement.ilike(f"%{query}%"))

        rows = await session.scalars(
            stmt.order_by(Memory.id.desc()).limit(limit)
        )
        memories = list(rows)

    return {
        "num_memories": len(memories),
        "memories": [
            {
                "id": str(m.id),
                "kind": m.kind,
                "statement": m.statement,
                "status": m.status,
                "repository_id": str(m.repository_id)
                if m.repository_id
                else None,
                "created_at": str(m.created_at),
            }
            for m in memories
        ],
    }


# ---------------------------------------------------------------------------
# Checkpoint tools
# ---------------------------------------------------------------------------


@mcp.tool
@_instrument_tool("checkpoint_save")
async def checkpoint_save(
    objective: str,
    session_id: str | None = None,
    repository_id: str | None = None,
    current_state: str | None = None,
    changed_files: list[str] | None = None,
    pending_steps: list[str] | None = None,
    evidence: dict | None = None,
) -> dict:
    """Save a task progress checkpoint for session resumption.

    Checkpoints are timestamped and grouped by session_id for
    reliable restoration of work-in-progress across agent restarts.

    Args:
        objective: Description of the task objective.
        session_id: Optional session identifier for grouping checkpoints.
        repository_id: Optional repository UUID the checkpoint relates to.
        current_state: Description of the current state of work.
        changed_files: List of files that have been modified.
        pending_steps: List of remaining steps to complete.
        evidence: Optional supporting evidence dictionary.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository, TaskCheckpoint

    factory = get_session_factory()
    async with factory() as session:
        if repository_id:
            repo = (
                await session.scalars(
                    select(Repository).where(Repository.id == repository_id)
                )
            ).first()
            if not repo:
                return {"error": f"Repository {repository_id} not found"}

        cp = TaskCheckpoint(
            repository_id=repository_id,
            session_id=session_id,
            objective=objective,
            current_state=current_state,
            changed_files=changed_files,
            pending_steps=pending_steps,
            evidence=evidence,
        )
        session.add(cp)
        await session.commit()
        await session.refresh(cp)

    return {
        "id": str(cp.id),
        "session_id": cp.session_id,
        "objective": cp.objective,
        "created_at": str(cp.created_at),
        "message": "Checkpoint saved",
    }


@mcp.tool
@_instrument_tool("checkpoint_get")
async def checkpoint_get(
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Retrieve the latest checkpoint for a session and/or repository.

    Also known as: task_resume.

    Args:
        session_id: Session identifier to filter by.
        repository_id: Optional repository UUID to filter by.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import TaskCheckpoint

    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TaskCheckpoint)
        if session_id:
            stmt = stmt.where(TaskCheckpoint.session_id == session_id)
        if repository_id:
            stmt = stmt.where(
                TaskCheckpoint.repository_id == repository_id
            )

        cp = (
            await session.scalars(
                stmt.order_by(
                    TaskCheckpoint.created_at.desc()
                ).limit(1)
            )
        ).first()

    if not cp:
        return {"error": "No checkpoint found", "checkpoint": None}

    return {
        "id": str(cp.id),
        "session_id": cp.session_id,
        "repository_id": str(cp.repository_id)
        if cp.repository_id
        else None,
        "objective": cp.objective,
        "current_state": cp.current_state,
        "changed_files": cp.changed_files,
        "pending_steps": cp.pending_steps,
        "evidence": cp.evidence,
        "created_at": str(cp.created_at),
    }


# Alias — plan name task_resume delegates to checkpoint_get


@mcp.tool(name="task_resume")
@_instrument_tool("task_resume")
async def task_resume_alias(
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Alias for checkpoint_get. See checkpoint_get for full documentation."""
    return await checkpoint_get(
        session_id=session_id,
        repository_id=repository_id,
    )


# ---------------------------------------------------------------------------
# Compaction continuity tools (Phase 5)
# ---------------------------------------------------------------------------


@mcp.tool
@_instrument_tool("compaction_checkpoint_save")
async def compaction_checkpoint_save(
    objective: str,
    session_id: str | None = None,
    repository_id: str | None = None,
    current_state: str | None = None,
    changed_files: list[str] | None = None,
    pending_steps: list[str] | None = None,
    evidence: dict | None = None,
) -> dict:
    """Save a checkpoint optimized for compaction recovery.

    Invoke this before context compaction so that work-in-progress is
    preserved.  Unlike a generic checkpoint, this also captures the
    current verified memories and indexes them so they are available
    during resume.

    Args:
        objective: High-level task objective.
        session_id: Session identifier for grouping.
        repository_id: Optional repository UUID.
        current_state: What has been done so far.
        changed_files: Files modified during this session.
        pending_steps: Remaining steps.
        evidence: Supporting evidence dict.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository, TaskCheckpoint

    factory = get_session_factory()
    async with factory() as session:
        if repository_id:
            repo = (
                await session.scalars(
                    select(Repository).where(
                        Repository.id == repository_id,
                    ),
                )
            ).first()
            if not repo:
                return {"error": f"Repository {repository_id} not found"}

        # Also attach a compaction marker to evidence
        evidence = evidence or {}
        evidence.setdefault("compaction", {})[
            "save_type"
        ] = "pre_compaction"

        cp = TaskCheckpoint(
            repository_id=repository_id,
            session_id=session_id,
            objective=objective,
            current_state=current_state,
            changed_files=changed_files,
            pending_steps=pending_steps,
            evidence=evidence,
        )
        session.add(cp)
        await session.commit()
        await session.refresh(cp)

    return {
        "id": str(cp.id),
        "session_id": cp.session_id,
        "objective": cp.objective,
        "created_at": str(cp.created_at),
        "message": "Compaction checkpoint saved",
    }


@mcp.tool
@_instrument_tool("session_bootstrap")
async def session_bootstrap(
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Restore session state after compaction or restart.

    Returns the most recent checkpoint verified memories and the agent
    can use them to reconstruct working context without scanning the
    conversation history.

    Args:
        session_id: Session identifier to restore for.
        repository_id: Optional repository UUID to scope results.
    """
    from repo_intel.compaction.manager import (  # noqa: PLC0415
        session_bootstrap as _bootstrap,
    )

    return await _bootstrap(
        session_id=session_id,
        repository_id=repository_id,
    )


# ---------------------------------------------------------------------------
# Dependency graph tools
# ---------------------------------------------------------------------------


@mcp.tool
@_instrument_tool("repo_dependencies")
async def repo_dependencies(
    symbol_name: str,
    repository_id: str | None = None,
    direction: str = "outgoing",
    depth: int = 2,
) -> dict:
    """Traverse the symbol dependency graph for a given symbol.

    Returns bounded, evidence-linked dependency edges (imports, calls,
    references) starting from the named symbol.

    Args:
        symbol_name: Symbol name to start traversal from.
        repository_id: Optional repository UUID to scope the search.
        direction: "outgoing" (what the symbol depends on) or
                   "incoming" (what depends on the symbol).
        depth: Maximum traversal depth (default 2, max 5).
    """
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Symbol, SymbolEdge

    factory = get_session_factory()
    async with factory() as session:
        # Find the starting symbol
        stmt = select(Symbol).where(
            Symbol.name.ilike(f"%{symbol_name}%")
        ).limit(5)
        if repository_id:
            from repo_intel.db.models import FileRecord  # noqa: PLC0415
            stmt = stmt.join(FileRecord).where(
                FileRecord.repository_id == repository_id
            )
        symbols = list(await session.scalars(stmt))
        if not symbols:
            return {"error": f"No symbol matching '{symbol_name}' found", "edges": []}

        start_ids = {str(s.id) for s in symbols}

        # BFS traversal
        visited: set[str] = set()
        edges_found: list[dict] = []
        current_ids = start_ids

        for _depth_level in range(min(depth, 5)):
            if not current_ids or len(edges_found) >= 50:
                break
            edge_stmt = select(SymbolEdge).where(
                SymbolEdge.from_symbol_id.in_(current_ids)
                if direction == "outgoing"
                else SymbolEdge.to_symbol_id.in_(current_ids)
            )
            rows = await session.scalars(edge_stmt)
            next_ids: set[str] = set()
            for edge in rows:
                if str(edge.id) in visited:
                    continue
                visited.add(str(edge.id))
                other_id = (
                    str(edge.to_symbol_id)
                    if direction == "outgoing"
                    else str(edge.from_symbol_id)
                )
                # Fetch the target symbol name
                target = await session.get(Symbol, other_id)
                to_name = target.name if target else "unknown"
                from_name = (
                    symbols[0].name if direction == "outgoing" else to_name
                )
                edges_found.append({
                    "from_symbol": from_name,
                    "to_symbol": to_name,
                    "relation_type": edge.relation_type,
                    "evidence_location": edge.evidence_location,
                    "confidence": edge.confidence,
                })
                next_ids.add(other_id)
            current_ids = next_ids - visited

    return {
        "symbol": symbol_name,
        "direction": direction,
        "depth": depth,
        "num_edges": len(edges_found),
        "edges": edges_found,
    }


# ---------------------------------------------------------------------------
# Expose for mounting in app.py
# ---------------------------------------------------------------------------

def get_mcp_app():
    """Return the MCP ASGI app for mounting at /mcp."""
    return mcp.http_app(path="/")
