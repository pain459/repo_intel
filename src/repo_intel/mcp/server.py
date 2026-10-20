"""MCP tools for repo_intel, usable by OpenCode and other MCP clients."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (self-contained, no external MCP framework dependency yet).
# Each tool returns a dict suitable for serialisation to JSON.
# ---------------------------------------------------------------------------


async def tool_repo_list(session_factory) -> dict:
    """List registered repositories and their index freshness."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from repo_intel.db.models import (
        FileRecord,
        IndexGeneration,
        Repository,
    )

    async with session_factory() as session:
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
                    select(func.count()).select_from(FileRecord).where(
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


async def tool_index_status(session_factory, repository_id: str) -> dict:
    """Get the index status for a single repository."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import (
        IndexGeneration,
        IndexJob,
        Repository,
    )

    async with session_factory() as session:
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


async def tool_repo_search(
    session_factory,
    query: str,
    repository_id: str | None = None,
    limit: int = 10,
    exclude_doc_chunks: bool = False,
) -> dict:
    """Hybrid search across indexed repositories."""
    from repo_intel.retrieval.search import hybrid_search
    from repo_intel.retrieval.types import SearchRequest

    async with session_factory() as session:
        request = SearchRequest(
            query=query,
            repository_id=repository_id,
            limit=limit,
            exclude_doc_chunks=exclude_doc_chunks,
        )
        results = await hybrid_search(session, request)

    return {
        "query": query,
        "repository_id": repository_id,
        "num_results": len(results),
        "results": [
            {
                "chunk_id": str(r.chunk_id),
                "file": r.path,
                "path": r.path,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "content_hash": r.content_hash,
                "text": r.text[:2000],
                "retrieval_methods": r.retrieval_methods,
                "score": round(r.score, 6),
                "relevance_reason": r.relevance_reason,
                "generation_created_at": r.generation_created_at,
                "is_stale": r.is_stale,
                "is_truncated": r.is_truncated,
                "evidence_kind": r.evidence_kind,
                "metadata": {
                    "generation_created_at": r.generation_created_at,
                    "is_stale": r.is_stale,
                    "is_truncated": r.is_truncated,
                    "evidence_kind": r.evidence_kind,
                    "retrieval_methods": r.retrieval_methods,
                    "relevance_reason": r.relevance_reason,
                    "content_hash": r.content_hash,
                },
            }
            for r in results
        ],
    }


async def tool_repo_symbol(
    session_factory,
    symbol_name: str,
    repository_id: str | None = None,
) -> dict:
    """Find symbol definitions by name."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, IndexGeneration, Symbol

    async with session_factory() as session:
        # Resolve active generation IDs to avoid returning stale duplicates
        gen_stmt = (
            select(IndexGeneration.id)
            .where(IndexGeneration.state == "active")
        )
        if repository_id:
            gen_stmt = gen_stmt.where(
                IndexGeneration.repository_id == repository_id,
            )
        active_gen_ids = [str(gid) for gid in await session.scalars(gen_stmt)]

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

    results = []
    for symbol, path in rows:
        results.append({
            "name": symbol.name,
            "kind": symbol.kind,
            "file": path,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "source": "symbol",
        })

    # Fallback: search Chunk.symbol_name if Symbol table returned nothing
    if not results:
        from repo_intel.db.models import Chunk  # noqa: PLC0415

        async with session_factory() as session:
            # Resolve active generation IDs for defense-in-depth
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
            if repository_id:
                chunk_stmt = chunk_stmt.where(
                    FileRecord.repository_id == repository_id,
                )
            chunk_rows = await session.execute(chunk_stmt)
            for cname, cstart, cend, ckind, cpath in chunk_rows:
                results.append({
                    "name": cname,
                    "kind": ckind or "unknown",
                    "file": cpath,
                    "start_line": cstart,
                    "end_line": cend,
                    "source": "chunk_fallback",
                })

    return {"symbol": symbol_name, "definitions": results}


async def tool_repo_context(
    session_factory,
    task_description: str,
    repository_id: str | None = None,
    token_budget: int = 12_000,
) -> dict:
    """Build a curated evidence pack for a task description."""
    from repo_intel.retrieval.search import hybrid_search
    from repo_intel.retrieval.types import SearchRequest

    async with session_factory() as session:
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


# ---------------------------------------------------------------------------
# File listing tools
# ---------------------------------------------------------------------------


async def tool_repo_list_files(
    session_factory,
    repository_id: str,
    glob_pattern: str | None = None,
) -> dict:
    """List indexed files in a repository.

    *glob_pattern* can be e.g. ``*.py`` to narrow results.
    """
    import fnmatch  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, Repository  # noqa: PLC0415

    async with session_factory() as session:
        repo = await session.get(Repository, repository_id)
        if not repo:
            return {"error": f"Repository {repository_id} not found"}

        q = select(FileRecord).where(
            FileRecord.repository_id == repo.id,
            FileRecord.deleted == False,  # noqa: E712
        ).order_by(FileRecord.relative_path)
        rows = list(await session.scalars(q))

    files = [
        {
            "relative_path": f.relative_path,
            "language": f.language,
            "size_bytes": f.size_bytes,
        }
        for f in rows
    ]
    # Apply glob filter after fetching (fnmatch supports simple wildcards)
    if glob_pattern:
        files = [
            f for f in files
            if fnmatch.fnmatch(f["relative_path"], glob_pattern)
        ]

    return {
        "repository_id": repository_id,
        "file_count": len(files),
        "files": files,
    }


# ---------------------------------------------------------------------------
# File reading tools
# ---------------------------------------------------------------------------


async def tool_repo_read_file(
    session_factory,
    relative_path: str,
    repository_id: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Read source content from a file in a registered repository."""
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
        return {"error": "repository_id is required"}

    async with session_factory() as session:
        repo = await session.get(Repository, repository_id)
        if not repo:
            return {"error": f"Repository {repository_id} not found"}

        if not is_safe_relative_path(relative_path):
            return {"error": "Invalid path"}

        try:
            abs_path = resolve_safe(repo.git_path, relative_path)
        except PathTraversalError:
            return {"error": "Path traversal blocked"}

        fr_rows = await session.scalars(
            select(FileRecord).where(
                FileRecord.repository_id == repository_id,
                FileRecord.relative_path == relative_path,
                FileRecord.deleted == False,  # noqa: E712
            )
        )
        file_rec = fr_rows.first()
        if not file_rec:
            return {"error": f"File '{relative_path}' not indexed"}

        if is_secret_file(relative_path):
            return {"error": "Secret file access blocked"}

        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except (OSError, PermissionError) as exc:
            return {"error": str(exc), "path": relative_path}

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
            is_fresh = disk_hash == file_rec.content_hash

        redacted = redact_content(raw)
        lines = redacted.cleaned_text.splitlines(keepends=True)
        if start_line is not None and end_line is not None:
            sliced = lines[start_line - 1: end_line]
        elif start_line is not None:
            sliced = lines[start_line - 1:]
        elif end_line is not None:
            sliced = lines[:end_line]
        else:
            sliced = lines[:5000]

        return {
            "path": relative_path,
            "start_line": start_line or 1,
            "end_line": end_line or len(lines),
            "total_lines": len(lines),
            "lines_returned": len(sliced),
            "is_truncated": len(sliced) < len(lines),
            "content_hash": file_rec.content_hash,
            "is_fresh": is_fresh,
            "evidence_kind": "exact_source" if is_fresh else "stale",
            "redacted_patterns": (
                redacted.pattern_labels
                if redacted.patterns_matched > 0
                else []
            ),
            "content": "".join(sliced),
        }


# ---------------------------------------------------------------------------
# Dependency graph tools
# ---------------------------------------------------------------------------


async def tool_repo_dependencies(
    session_factory,
    symbol_name: str,
    repository_id: str | None = None,
    direction: str = "outgoing",
    depth: int = 2,
) -> dict:
    """Traverse the symbol dependency graph for a given symbol."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import (  # noqa: PLC0415
        FileRecord,
        IndexGeneration,
        Symbol,
        SymbolEdge,
    )

    async with session_factory() as session:
        # Resolve active generation IDs
        gen_stmt = (
            select(IndexGeneration.id)
            .where(IndexGeneration.state == "active")
        )
        if repository_id:
            gen_stmt = gen_stmt.where(
                IndexGeneration.repository_id == repository_id,
            )
        active_gen_ids = [str(gid) for gid in await session.scalars(gen_stmt)]

        # Find starting symbol (only from active generations)
        stmt = select(Symbol).where(
            Symbol.name.ilike(f"%{symbol_name}%"),
            Symbol.generation_id.in_(active_gen_ids),
        ).limit(5)
        if repository_id:
            stmt = stmt.join(FileRecord).where(
                FileRecord.repository_id == repository_id,
            )
        symbols = list(await session.scalars(stmt))
        if not symbols:
            return {
                "error": f"No symbol matching '{symbol_name}' found",
                "edges": [],
            }

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
                    # from→to is caller→callee (edge direction = call direction)
                    from_sym = await session.get(Symbol, str(edge.from_symbol_id))
                    to_sym = await session.get(Symbol, other_id)
                    from_name = from_sym.name if from_sym else "unknown"
                    to_name = to_sym.name if to_sym else "unknown"
                else:
                    other_id = str(edge.from_symbol_id)
                    # for incoming, edge direction is callee→caller,
                    # so from=caller, to=target (callee)
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
# Memory tools
# ---------------------------------------------------------------------------


async def tool_memory_write(
    session_factory,
    kind: str,
    statement: str,
    repository_id: str | None = None,
    evidence: dict | None = None,
    source_commit: str | None = None,
    author: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Write a new agent memory."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Memory, Repository  # noqa: PLC0415

    async with session_factory() as session:
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
            session_id=session_id,
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


async def tool_memory_read(
    session_factory,
    query: str | None = None,
    repository_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    session_id: str | None = None,
) -> dict:
    """Read agent memories, optionally filtered and scored."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Memory  # noqa: PLC0415

    async with session_factory() as session:
        stmt = select(Memory)
        if repository_id:
            stmt = stmt.where(Memory.repository_id == repository_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        if query:
            stmt = stmt.where(Memory.statement.ilike(f"%{query}%"))
        if session_id:
            stmt = stmt.where(Memory.session_id == session_id)

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
                "repository_id": str(m.repository_id) if m.repository_id else None,
                "evidence": m.evidence,
                "source_commit": m.source_commit,
                "author": m.author,
                "session_id": m.session_id,
                "created_at": str(m.created_at),
            }
            for m in memories
        ],
    }


# ---------------------------------------------------------------------------
# Compaction & session recovery tools
# ---------------------------------------------------------------------------


async def tool_compaction_checkpoint_save(
    session_factory,
    objective: str,
    session_id: str | None = None,
    repository_id: str | None = None,
    current_state: str | None = None,
    changed_files: list[str] | None = None,
    pending_steps: list[str] | None = None,
    evidence: dict | None = None,
) -> dict:
    """Save a checkpoint optimized for compaction recovery."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository, TaskCheckpoint  # noqa: PLC0415

    async with session_factory() as session:
        if repository_id:
            repo = (
                await session.scalars(
                    select(Repository).where(Repository.id == repository_id)
                )
            ).first()
            if not repo:
                return {"error": f"Repository {repository_id} not found"}

        evidence = evidence or {}
        evidence.setdefault("compaction", {})["save_type"] = "pre_compaction"

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


async def tool_session_bootstrap(
    session_factory,
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Restore session state after compaction or restart."""
    from repo_intel.compaction.manager import (  # noqa: PLC0415
        session_bootstrap as _bootstrap,
    )

    return await _bootstrap(
        session_id=session_id,
        repository_id=repository_id,
    )


# ---------------------------------------------------------------------------
# Checkpoint tools
# ---------------------------------------------------------------------------


async def tool_checkpoint_save(
    session_factory,
    objective: str,
    session_id: str | None = None,
    repository_id: str | None = None,
    current_state: str | None = None,
    changed_files: list[str] | None = None,
    pending_steps: list[str] | None = None,
    evidence: dict | None = None,
) -> dict:
    """Save a task checkpoint."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository, TaskCheckpoint  # noqa: PLC0415

    async with session_factory() as session:
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


async def tool_checkpoint_get(
    session_factory,
    session_id: str | None = None,
    repository_id: str | None = None,
) -> dict:
    """Get the latest checkpoint for a session/repo combination."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import TaskCheckpoint  # noqa: PLC0415

    async with session_factory() as session:
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
        "repository_id": str(cp.repository_id) if cp.repository_id else None,
        "objective": cp.objective,
        "current_state": cp.current_state,
        "changed_files": cp.changed_files,
        "pending_steps": cp.pending_steps,
        "evidence": cp.evidence,
        "created_at": str(cp.created_at),
    }
