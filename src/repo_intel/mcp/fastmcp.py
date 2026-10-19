"""FastMCP server wrapping repo_intel tools for OpenCode integration."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

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
# Tool registrations (async, using the existing session factory pattern)
# ---------------------------------------------------------------------------


@mcp.tool
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
async def memory_write(
    kind: str,
    statement: str,
    repository_id: str | None = None,
    evidence: dict | None = None,
    source_commit: str | None = None,
    author: str | None = None,
) -> dict:
    """Write a new agent memory (preference, observation, or instruction).

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


@mcp.tool
async def memory_read(
    query: str | None = None,
    repository_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict:
    """Read agent memories with optional filtering and full-text search.

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
async def checkpoint_get(
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Retrieve the latest checkpoint for a session and/or repository.

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


# ---------------------------------------------------------------------------
# Expose for mounting in app.py
# ---------------------------------------------------------------------------

def get_mcp_app():
    """Return the MCP ASGI app for mounting at /mcp."""
    return mcp.http_app(path="/")
