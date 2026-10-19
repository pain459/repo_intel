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
) -> dict:
    """Hybrid search across indexed repositories."""
    from repo_intel.retrieval.search import hybrid_search
    from repo_intel.retrieval.types import SearchRequest

    async with session_factory() as session:
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

    from repo_intel.db.models import FileRecord, Symbol

    async with session_factory() as session:
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
            }
            for r in results
        ],
    }
