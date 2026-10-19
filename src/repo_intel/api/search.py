"""Search REST API endpoint."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repo_intel.retrieval.search import hybrid_search
from repo_intel.retrieval.types import SearchResult

router = APIRouter(prefix="/api/search", tags=["search"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048, description="Search query text")
    repository_id: uuid.UUID | None = Field(
        None, description="Scope to a specific repository (search all if omitted)"
    )
    limit: int = Field(10, ge=1, le=100, description="Maximum results to return")
    token_budget: int = Field(
        12_000, ge=100, le=128_000, description="Token budget for the response"
    )
    include_content: bool = Field(True, description="Whether to include chunk text")


class HitOut(BaseModel):
    chunk_id: uuid.UUID
    path: str
    start_line: int
    end_line: int
    content_hash: str
    text: str = ""
    retrieval_methods: list[str] = []
    score: float = 0.0
    relevance_reason: str = ""
    generation_created_at: str = ""
    is_stale: bool = False


class SearchResponse(BaseModel):
    query: str
    limit: int
    token_budget: int
    estimated_tokens: int = 0
    results: list[HitOut] = []
    elapsed_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/")
async def search(body: SearchQuery) -> SearchResponse:
    """Execute a hybrid search query (exact + FTS + vector)."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import Repository  # noqa: PLC0415
    from repo_intel.db.session import get_session_factory  # noqa: PLC0415
    from repo_intel.retrieval.types import SearchRequest as InternalRequest  # noqa: PLC0415

    t0 = time.monotonic()

    # Validate repository scope if given
    if body.repository_id:
        async with get_session_factory()() as validate_session:
            repo = (
                await validate_session.scalars(
                    select(Repository).where(Repository.id == body.repository_id)
                )
            ).first()
            if not repo:
                raise HTTPException(404, f"Repository {body.repository_id} not found")

    async with get_session_factory()() as session:
        request = InternalRequest(
            query=body.query,
            repository_id=str(body.repository_id) if body.repository_id else None,
            limit=body.limit,
            token_budget=body.token_budget,
            include_content=body.include_content,
        )

        hits: list[SearchResult] = await hybrid_search(session, request)

    # Compute total tokens
    total_tokens = sum(
        h.estimated_tokens or max(len(h.text) // 4, 1) for h in hits
    )

    elapsed = int((time.monotonic() - t0) * 1000)

    # Collect freshness data for event recording
    selected_chunk_ids = [str(h.chunk_id) for h in hits]
    stale_count = sum(1 for h in hits if h.is_stale)
    # Grab the first result's generation if available
    first_gen = None
    for h in hits:
        gid = h.generation_id
        if gid:
            if isinstance(gid, uuid.UUID):
                first_gen = gid
            else:
                first_gen = uuid.UUID(str(gid))
            break

    # Record retrieval event
    await _record_event(
        repository_id=body.repository_id,
        query=body.query,
        num_results=len(hits),
        token_budget=body.token_budget,
        estimated_tokens=total_tokens,
        elapsed_ms=elapsed,
        selected_chunk_ids=selected_chunk_ids,
        generation_id=first_gen,
        stale_count=stale_count,
    )

    warnings: list[str] = []
    if total_tokens > body.token_budget:
        warnings.append(f"Token budget exceeded: {total_tokens} > {body.token_budget}")
    if not hits:
        warnings.append("No results found. Try broadening the query or re-indexing.")

    # Warn about stale index data
    if stale_count > 0:
        warnings.append(
            f"{stale_count}/{len(hits)} hit(s) may be stale "
            "(index is more than 1 hour old). Consider re-indexing."
        )

    return SearchResponse(
        query=body.query,
        limit=body.limit,
        token_budget=body.token_budget,
        estimated_tokens=total_tokens,
        results=[
            HitOut(
                chunk_id=r.chunk_id,
                path=r.path,
                start_line=r.start_line,
                end_line=r.end_line,
                content_hash=r.content_hash,
                text=r.text if body.include_content else "",
                retrieval_methods=r.retrieval_methods,
                score=round(r.score, 6),
                relevance_reason=r.relevance_reason,
                generation_created_at=r.generation_created_at,
                is_stale=r.is_stale,
            )
            for r in hits
        ],
        elapsed_ms=elapsed,
        warnings=warnings,
    )


async def _record_event(
    repository_id: uuid.UUID | None,
    query: str,
    num_results: int,
    token_budget: int,
    estimated_tokens: int,
    elapsed_ms: int,
    selected_chunk_ids: list[str] | None = None,
    generation_id: uuid.UUID | None = None,
    stale_count: int = 0,
) -> None:
    """Log a retrieval event for observability."""
    import uuid as _uuid  # noqa: PLC0415

    from sqlalchemy import text  # noqa: PLC0415

    from repo_intel.db.session import get_session_factory  # noqa: PLC0415
    request_id = _uuid.uuid4().hex[:32]

    try:
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO retrieval_events
                        (repository_id, request_id, query, num_results, token_budget,
                          estimated_tokens_returned, elapsed_ms, generation_id,
                          selected_chunk_ids, stale_count)
                    VALUES (:repo_id, :request_id, :query, :num, :budget,
                            :tokens, :elapsed, :gen_id, :chunk_ids, :stale)
                    """
                ).bindparams(
                    repo_id=str(repository_id) if repository_id else None,
                    request_id=request_id,
                    query=query[:500],  # truncate for storage
                    num=num_results,
                    budget=token_budget,
                    tokens=estimated_tokens,
                    elapsed=elapsed_ms,
                    gen_id=str(generation_id) if generation_id else None,
                    chunk_ids=selected_chunk_ids,
                    stale=stale_count,
                )
            )
            await session.commit()
    except Exception:
        # Don't let logging break the search response
        pass
