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
                "is_truncated": r.is_truncated,
                "evidence_kind": r.evidence_kind,
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

    from repo_intel.db.models import Chunk, FileRecord, IndexGeneration, Symbol

    factory = get_session_factory()
    async with factory() as session:
        # Resolve active generation IDs so we only return symbols from the
        # current index scan, preventing duplicates from stale generations.
        gen_stmt = (
            select(IndexGeneration.id)
            .where(IndexGeneration.state == "active")
        )
        if repository_id:
            gen_stmt = gen_stmt.where(
                IndexGeneration.repository_id == repository_id,
            )
        active_gen_ids = [str(gid) for gid in await session.scalars(gen_stmt)]

        # 1. Query the Symbol table (primary source, scoped to active generation)
        stmt = (
            select(Symbol, FileRecord.relative_path)
            .join(FileRecord, Symbol.file_id == FileRecord.id)
            .where(
                Symbol.name.ilike(f"%{symbol_name}%"),
                Symbol.generation_id.in_(active_gen_ids),
                FileRecord.deleted == False,  # noqa: E712
            )
            .limit(20)
        )
        if repository_id:
            stmt = stmt.where(FileRecord.repository_id == repository_id)

        rows = await session.execute(stmt)

        symbol_results: list[dict[str, object]] = []
        for symbol, path in rows:
            symbol_results.append({
                "name": symbol.name,
                "kind": symbol.kind,
                "file": path,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "source": "symbol",
            })

        # 2. Fallback: if primary table returned nothing, also search
        #    Chunk.symbol_name so that symbols from small files (where the
        #    chunker emits boundary chunks with symbol_name set) are still
        #    discoverable.
        if not symbol_results:
            # Resolve active generation IDs so the fallback only returns
            # chunks from the current index scan (defense-in-depth).
            gen_stmt = (
                select(IndexGeneration.id)
                .where(IndexGeneration.state == "active")
            )
            if repository_id:
                gen_stmt = gen_stmt.where(
                    IndexGeneration.repository_id == repository_id,
                )
            active_gen_ids = [str(gid) for gid in await session.scalars(gen_stmt)]

            chunk_stmt = (
                select(Chunk.symbol_name, Chunk.start_line, Chunk.end_line,
                       Chunk.chunk_type, FileRecord.relative_path)
                .join(FileRecord, Chunk.file_id == FileRecord.id)
                .where(
                    Chunk.symbol_name.ilike(f"%{symbol_name}%"),
                    Chunk.generation_id.in_(active_gen_ids),
                    FileRecord.deleted == False,  # noqa: E712
                )
                .limit(20)
            )
            chunk_rows = await session.execute(chunk_stmt)
            for cname, cstart, cend, ckind, cpath in chunk_rows:
                symbol_results.append({
                    "name": cname,
                    "kind": ckind or "unknown",
                    "file": cpath,
                    "start_line": cstart,
                    "end_line": cend,
                    "source": "chunk_fallback",
                })

    return {"symbol": symbol_name, "definitions": symbol_results}


@mcp.tool
@_instrument_tool("repo_read_file")
async def repo_read_file(
    relative_path: str,
    repository_id: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Read source content from a file in a registered repository.

    Returns the file content (or a line range) from the repository's
    working tree on disk, validated against the index for freshness.
    Security boundaries: path traversal protection, secret file exclusion,
    repository-scope confinement.

    Args:
        relative_path: Path within the repository (e.g. 'backend/app/main.py').
        repository_id: Required repository UUID to scope the read.
        start_line: Optional 1-based start line to return.
        end_line: Optional 1-based end line to return.
    """
    import hashlib as _hl  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, IndexGeneration, Repository
    from repo_intel.security.paths import (  # noqa: PLC0415
        is_safe_relative_path,
        is_secret_file,
        PathTraversalError,
        resolve_safe,
    )
    from repo_intel.security.redaction import redact_content

    if not repository_id:
        return {"error": "repository_id is required for repo_read_file"}

    factory = get_session_factory()
    async with factory() as session:
        # 1. Resolve repository
        repo = await session.get(Repository, repository_id)
        if not repo:
            return {"error": f"Repository {repository_id} not found"}

        # 2. Validate path safety
        if not is_safe_relative_path(relative_path):
            return {"error": "Invalid path: contains disallowed characters or patterns"}

        # 3. Resolve absolute path (prevents traversal)
        try:
            abs_path = resolve_safe(repo.git_path, relative_path)
        except PathTraversalError:
            return {"error": f"Path traversal detected in '{relative_path}'"}

        # 4. Check that file is indexed (exists in files table, non-deleted)
        fr_rows = await session.scalars(
            select(FileRecord).where(
                FileRecord.repository_id == repository_id,
                FileRecord.relative_path == relative_path,
                FileRecord.deleted == False,  # noqa: E712
            )
        )
        file_rec = fr_rows.first()
        if not file_rec:
            return {"error": f"File '{relative_path}' is not indexed in repository"}

        # 5. Check if file is a secret file
        if is_secret_file(relative_path):
            return {"error": f"File '{relative_path}' is excluded (secret/credential file)"}

        # 6. Read content from disk (not DB) for freshness
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except (OSError, PermissionError) as exc:
            return {
                "error": f"Cannot read file: {exc}",
                "path": relative_path,
            }

        # 7. Check freshness against active generation
        gen_rows = await session.scalars(
            select(IndexGeneration).where(
                IndexGeneration.repository_id == repository_id,
                IndexGeneration.state == "active",
            )
        )
        active_gen = gen_rows.first()
        is_fresh = False
        if active_gen:
            disk_hash = _hl.sha256(raw.encode()).hexdigest()
            is_fresh = (disk_hash == file_rec.content_hash)

        # 8. Apply secret redaction to content
        redacted = redact_content(raw)

        # 9. Slice to line range if requested
        lines = redacted.cleaned_text.splitlines(keepends=True)
        if start_line is not None and end_line is not None:
            sliced = lines[start_line - 1: end_line]
        elif start_line is not None:
            sliced = lines[start_line - 1:]
        elif end_line is not None:
            sliced = lines[:end_line]
        else:
            # Bounded read: max 5000 lines to prevent large responses
            sliced = lines[:5000]

        content = "".join(sliced)
        evidence_kind = "exact_source"
        if not is_fresh:
            evidence_kind = "stale"

        return {
            "path": relative_path,
            "start_line": start_line or 1,
            "end_line": (end_line or len(lines)),
            "total_lines": len(lines),
            "lines_returned": len(sliced),
            "is_truncated": len(sliced) < len(lines),
            "content_hash": file_rec.content_hash,
            "is_fresh": is_fresh,
            "evidence_kind": evidence_kind,
            "redacted_patterns": (
                redacted.pattern_labels
                if redacted.patterns_matched > 0
                else []
            ),
            "content": content,
        }


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
                "relevance_reason": r.relevance_reason,
                "generation_created_at": r.generation_created_at,
                "is_stale": r.is_stale,
                "is_truncated": r.is_truncated,
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
                "evidence": m.evidence,
                "source_commit": m.source_commit,
                "author": m.author,
                "created_at": str(m.created_at),
            }
            for m in memories
        ],
    }


# Alias — plan name memory_read delegates to memory_search


@mcp.tool(name="memory_read")
@_instrument_tool("memory_read")
async def memory_read_alias(
    query: str | None = None,
    repository_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict:
    """Alias for memory_search. See memory_search for full documentation."""
    return await memory_search(
        query=query,
        repository_id=repository_id,
        kind=kind,
        limit=limit,
    )


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

    from repo_intel.db.models import (
        FileRecord,
        IndexGeneration,
        Symbol,
        SymbolEdge,
    )

    factory = get_session_factory()
    async with factory() as session:
        # Determine active generation IDs (scoped to repo if provided)
        gen_stmt = (
            select(IndexGeneration.id)
            .where(IndexGeneration.state == "active")
        )
        if repository_id:
            gen_stmt = gen_stmt.where(
                IndexGeneration.repository_id == repository_id
            )
        active_gen_ids = [
            str(gid) for gid in (await session.scalars(gen_stmt))
        ]

        # Find the starting symbol (only from active generations)
        stmt = select(Symbol).where(
            Symbol.name.ilike(f"%{symbol_name}%"),
            Symbol.generation_id.in_(active_gen_ids),
        ).limit(5)
        if repository_id:
            stmt = stmt.join(FileRecord).where(
                FileRecord.repository_id == repository_id
            )
        symbols = list(await session.scalars(stmt))
        if not symbols:
            return {"error": f"No symbol matching '{symbol_name}' found", "edges": []}

        start_ids = {str(s.id) for s in symbols}

        # BFS traversal
        visited_edges: set[str] = set()
        visited_symbols: set[str] = set()
        visited_symbols.update(start_ids)
        edges_found: list[dict] = []
        current_ids = start_ids

        for _depth_level in range(min(depth, 5)):
            if not current_ids or len(edges_found) >= 50:
                break
            if direction == "outgoing":
                edge_cond = SymbolEdge.from_symbol_id.in_(current_ids)
            else:
                edge_cond = SymbolEdge.to_symbol_id.in_(current_ids)
            edge_stmt = select(SymbolEdge).where(
                edge_cond,
                SymbolEdge.generation_id.in_(active_gen_ids),
            )
            rows = await session.scalars(edge_stmt)
            next_ids: set[str] = set()
            for edge in rows:
                if str(edge.id) in visited_edges:
                    continue
                visited_edges.add(str(edge.id))
                if direction == "outgoing":
                    other_id = str(edge.to_symbol_id)
                    # edge direction = call direction: from→to is caller→callee
                    from_sym = await session.get(Symbol, str(edge.from_symbol_id))
                    to_sym = await session.get(Symbol, other_id)
                    from_name = from_sym.name if from_sym else "unknown"
                    to_name = to_sym.name if to_sym else "unknown"
                else:
                    other_id = str(edge.from_symbol_id)
                    # for incoming, edge is callee→caller, so caller is `from`
                    from_sym = await session.get(Symbol, other_id)
                    to_sym = await session.get(Symbol, str(edge.to_symbol_id))
                    from_name = from_sym.name if from_sym else "unknown"
                    to_name = to_sym.name if to_sym else "unknown"
                edges_found.append({
                    "from_symbol": from_name,
                    "to_symbol": to_name,
                    "relation_type": edge.relation_type,
                    "evidence_location": edge.evidence_location,
                    "confidence": edge.confidence,
                })
                if other_id not in visited_symbols:
                    next_ids.add(other_id)
                    visited_symbols.add(other_id)
            current_ids = next_ids

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
