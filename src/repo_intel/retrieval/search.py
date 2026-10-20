"""Hybrid search retrieval: exact + FTS + vector with reciprocal rank fusion."""

from __future__ import annotations

import logging
from datetime import UTC

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from repo_intel.db.models import Chunk, FileRecord, IndexGeneration
from repo_intel.indexing.embeddings.adapter import EmbeddingError, get_embedding
from repo_intel.retrieval.types import SearchRequest, SearchResult

logger = logging.getLogger(__name__)

# Reciprocal rank fusion constant (standard value from the paper)
_RRF_K = 60

# Characters-per-token estimate (matches chunker)
_CHARS_PER_TOKEN = 4

# How many candidates each sub-search may return
_CANDIDATE_LIMIT = 100

# Staleness threshold: if index is older than this, mark results as potentially stale
_STALE_THRESHOLD_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_active_generation_ids(
    session: AsyncSession,
    repository_id: str | None,
) -> list[str]:
    """Return the IDs of active index generations for the given scope."""
    gen_stmt = (
        select(IndexGeneration.id)
        .where(IndexGeneration.state == "active")
    )
    if repository_id:
        gen_stmt = gen_stmt.where(IndexGeneration.repository_id == repository_id)
    rows = await session.scalars(gen_stmt)
    return [str(gid) for gid in rows]


async def _get_generation_created_at(
    session: AsyncSession,
    generation_id: str,
) -> str:
    """Return the created_at timestamp string for a generation."""
    import uuid as _uuid  # noqa: PLC0415
    try:
        gid = str(_uuid.UUID(generation_id))
    except (ValueError, AttributeError):
        gid = generation_id
    gen = await session.get(IndexGeneration, gid)
    if gen and gen.created_at:
        return str(gen.created_at)
    return ""


# ---------------------------------------------------------------------------
# Exact match: filenames and identifiers
# ---------------------------------------------------------------------------


async def _exact_candidates(
    session: AsyncSession,
    query: str,
    repository_id: str | None,
    generation_ids: list[str],
    exclude_doc_chunks: bool = False,
) -> dict[str, int]:
    """Return {chunk_id: rank} for chunks whose path or symbol matches *query*."""
    if not generation_ids:
        return {}

    query_lower = query.lower()
    results: dict[str, int] = {}

    subquery = (
        select(Chunk.id, Chunk.symbol_name, FileRecord.relative_path)
        .join(FileRecord, Chunk.file_id == FileRecord.id)
        .where(
            Chunk.generation_id.in_(generation_ids),
            Chunk.stale == False,  # noqa: E712
            FileRecord.deleted == False,  # noqa: E712
        )
    )
    if repository_id:
        subquery = subquery.where(FileRecord.repository_id == repository_id)
    if exclude_doc_chunks:
        subquery = subquery.where(Chunk.chunk_type != "doc")

    rows = await session.execute(subquery)
    for chunk_id, symbol_name, rel_path in rows:
        cid = str(chunk_id)
        path_match = query_lower in (rel_path or "").lower()
        symbol_match = symbol_name and query_lower in symbol_name.lower()
        if path_match or symbol_match:
            results[cid] = len(results) + 1

    return results


# ---------------------------------------------------------------------------
# Lexical (FTS) candidates
# ---------------------------------------------------------------------------


async def _lexical_candidates(
    session: AsyncSession,
    query: str,
    repository_id: str | None,
    generation_ids: list[str],
    exclude_doc_chunks: bool = False,
) -> dict[str, int]:
    """Return {chunk_id: rank} for PostgreSQL FTS matches on chunk content."""
    if not generation_ids:
        return {}

    # Build the IN clause with proper placeholder + UUID casting
    placeholders = ",".join(
        f"CAST(:gen_{i} AS uuid)" for i in range(len(generation_ids))
    )

    doc_filter = "AND c.chunk_type != 'doc'" if exclude_doc_chunks else ""
    sql = text(
        f"""
        SELECT c.id, ts_rank_cd(to_tsvector('english', c.content),
                                plainto_tsquery('english', :query)) AS rank_val
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE c.generation_id IN ({placeholders})
          AND f.deleted = false
          AND c.stale = false
          {doc_filter}
          AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :query)
        ORDER BY rank_val DESC
        LIMIT :limit
        """
    )

    bind_params = {
        f"gen_{i}": gid for i, gid in enumerate(generation_ids)
    }
    bind_params["query"] = query
    bind_params["limit"] = _CANDIDATE_LIMIT

    rows = await session.execute(sql.bindparams(**bind_params))

    results: dict[str, int] = {}
    for idx, (chunk_id, _rank_val) in enumerate(rows, start=1):
        results[str(chunk_id)] = idx

    return results


# ---------------------------------------------------------------------------
# Semantic (vector) candidates
# ---------------------------------------------------------------------------


async def _semantic_candidates(
    session: AsyncSession,
    query: str,
    repository_id: str | None,
    generation_ids: list[str],
    exclude_doc_chunks: bool = False,
) -> dict[str, int]:
    """Return {chunk_id: rank} for pgvector cosine distance matches."""
    if not generation_ids:
        return {}

    try:
        query_embedding = await get_embedding(query)
    except EmbeddingError as exc:
        logger.warning("Could not get query embedding: %s", exc)
        return {}

    query_vec_text = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"

    # Build the IN clause with proper placeholder + UUID casting
    placeholders = ",".join(
        f"CAST(:gen_{i} AS uuid)" for i in range(len(generation_ids))
    )

    doc_filter = "AND c.chunk_type != 'doc'" if exclude_doc_chunks else ""

    bind_params = {f"gen_{i}": gid for i, gid in enumerate(generation_ids)}
    bind_params["query_vec"] = query_vec_text
    bind_params["limit"] = _CANDIDATE_LIMIT

    rows = await session.execute(
        text(
            f"""
            SELECT c.id, 1 - (c.embedding <=> CAST(:query_vec AS vector)) AS similarity
            FROM chunks c
            JOIN files f ON c.file_id = f.id
            WHERE c.generation_id IN ({placeholders})
              AND f.deleted = false
              AND c.stale = false
              {doc_filter}
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:query_vec AS vector)
            LIMIT :limit
            """
        ).bindparams(**bind_params)
    )

    results: dict[str, int] = {}
    for idx, (chunk_id, _similarity) in enumerate(rows, start=1):
        results[str(chunk_id)] = idx

    return results


# ---------------------------------------------------------------------------
# Symbol-neighbor expansion (bounded)
# ---------------------------------------------------------------------------


async def _symbol_candidates(
    session: AsyncSession,
    query: str,
    repository_id: str | None,
    generation_ids: list[str],
    exclude_doc_chunks: bool = False,
) -> dict[str, int]:
    """Return {chunk_id: rank} for chunks whose symbol_name matches *query*.

    When the query looks like an identifier (e.g. a function or class name),
    we return neighbors that share the same symbol name or reference it,
    bounded to _CANDIDATE_LIMIT results.
    """
    if not generation_ids:
        return {}

    # Only activate when query looks like an identifier
    # (short string, starts/ends with word chars, no spaces/punctuation)
    import re  # noqa: PLC0415
    if not re.match(r"^[a-zA-Z_]\w{0,127}$", query):
        return {}

    subquery = (
        select(Chunk.id, Chunk.symbol_name)
        .where(
            Chunk.generation_id.in_(generation_ids),
            Chunk.stale == False,  # noqa: E712
            Chunk.symbol_name.isnot(None),
        )
    )
    if exclude_doc_chunks:
        subquery = subquery.where(Chunk.chunk_type != "doc")
    rows = await session.execute(subquery)

    results: dict[str, int] = {}
    for chunk_id, symbol_name in rows:
        cid = str(chunk_id)
        if symbol_name and query.lower() in symbol_name.lower():
            results[cid] = len(results) + 1
            if len(results) >= _CANDIDATE_LIMIT:
                break

    return results


# ---------------------------------------------------------------------------
# Reciprocal rank fusion
# ---------------------------------------------------------------------------


def _rrf_fuse(
    candidate_sets: list[dict[str, int]],
    method_names: list[str],
) -> list[tuple[str, float, list[str]]]:
    """Fuse ranked candidate sets using reciprocal rank fusion.

    Returns [(chunk_id, fused_score, [methods])] sorted by descending score.
    """
    scores: dict[str, float] = {}
    methods_map: dict[str, set[str]] = {}

    for candidate_set, method_name in zip(candidate_sets, method_names, strict=False):
        for chunk_id, rank in candidate_set.items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
            methods_map.setdefault(chunk_id, set()).add(method_name)

    return [
        (cid, score, sorted(methods_map[cid]))
        for cid, score in sorted(scores.items(), key=lambda p: -p[1])
    ]


# ---------------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------------


async def _fetch_chunk_details(
    session: AsyncSession,
    chunk_ids: list[str],
) -> dict[str, SearchResult]:
    """Fetch full chunk details, keyed by chunk_id string."""
    if not chunk_ids:
        return {}

    rows = await session.execute(
        select(
            Chunk.id,
            FileRecord.relative_path,
            Chunk.start_line,
            Chunk.end_line,
            Chunk.content_hash,
            Chunk.content,
            Chunk.estimated_tokens,
            Chunk.generation_id,
        )
        .join(FileRecord, Chunk.file_id == FileRecord.id)
        .where(Chunk.id.in_(chunk_ids))
    )

    results: dict[str, SearchResult] = {}
    for (
        chunk_id,
        rel_path,
        start_line,
        end_line,
        content_hash,
        content,
        estimated_tokens,
        generation_id,
    ) in rows:
        cid = str(chunk_id)
        results[cid] = SearchResult(
            chunk_id=chunk_id,
            path=rel_path or "",
            start_line=start_line,
            end_line=end_line,
            content_hash=content_hash or "",
            text=content or "",
            estimated_tokens=estimated_tokens or 0,
        )
        # Store the generation_id for freshness lookup later (as string)
        results[cid].generation_id = str(generation_id)  # type: ignore[attr-defined]

    return results


# ---------------------------------------------------------------------------
# Overlap deduplication
# ---------------------------------------------------------------------------


def _dedup_overlapping_chunks(
    results: list[SearchResult],
) -> list[SearchResult]:
    """Remove chunks whose line range is fully subsumed by a higher-scored
    chunk from the same file.

    This prevents context packs from containing redundant overlapping excerpts
    when boundary-chunking small files produces multiple adjacent regions.
    """
    # Group by file path
    by_path: dict[str, list[SearchResult]] = {}
    for r in results:
        by_path.setdefault(r.path, []).append(r)

    kept: list[SearchResult] = []
    for path, chunks in by_path.items():
        # Sort by descending score so higher-scored chunks win
        chunks.sort(key=lambda c: c.score, reverse=True)
        # Track the union of line ranges already covered
        covered_intervals: list[tuple[int, int]] = []
        for c in chunks:
            if _range_covered(c.start_line, c.end_line, covered_intervals):
                continue
            kept.append(c)
            _merge_interval(covered_intervals, c.start_line, c.end_line)

    # Preserve the original fusion order (by score descending)
    kept.sort(key=lambda c: c.score, reverse=True)
    return kept


def _range_covered(
    start: int,
    end: int,
    intervals: list[tuple[int, int]],
) -> bool:
    """Return True if [start, end] is fully covered by the union of intervals."""
    for is_, ie_ in intervals:
        if start >= is_ and end <= ie_:
            return True
    return False


def _merge_interval(
    intervals: list[tuple[int, int]],
    start: int,
    end: int,
) -> None:
    """Add [start, end] to the interval list, merging overlaps in-place."""
    new_intervals: list[tuple[int, int]] = []
    s, e = start, end
    for is_, ie_ in intervals:
        if e + 1 < is_:
            # New interval ends before this one starts
            new_intervals.append((s, e))
            s, e = is_, ie_
        elif s - 1 > ie_:
            # This interval ends before the new one starts
            new_intervals.append((is_, ie_))
        else:
            # Overlap — merge
            s = min(s, is_)
            e = max(e, ie_)
    new_intervals.append((s, e))
    intervals.clear()
    intervals.extend(new_intervals)


# ---------------------------------------------------------------------------
# Token budget filtering
# ---------------------------------------------------------------------------


def _apply_token_budget(
    results: list[SearchResult],
    budget: int,
) -> list[SearchResult]:
    """Trim results so total estimated tokens stays within *budget*."""
    total_tokens = 0
    trimmed: list[SearchResult] = []
    for r in results:
        tokens = r.estimated_tokens or max(len(r.text) // _CHARS_PER_TOKEN, 1)
        if total_tokens + tokens > budget:
            remaining = budget - total_tokens
            max_chars = remaining * _CHARS_PER_TOKEN
            if max_chars > 50:
                r.is_truncated = True
                r.text = r.text[:max_chars] + "\n\n... [truncated]"
                trimmed.append(r)
            break
        total_tokens += tokens
        trimmed.append(r)
    return trimmed


# ---------------------------------------------------------------------------
# Main search entry point
# ---------------------------------------------------------------------------


async def hybrid_search(
    session: AsyncSession,
    request: SearchRequest,
) -> list[SearchResult]:
    """Execute the hybrid search pipeline.

    Steps
    -----
    0. Prompt-injection guard (sanitize query)
    1. Resolve active index generations for the requested scope
    2. Run exact, lexical (FTS), and semantic (vector) candidate retrieval
    3. Fuse via reciprocal rank fusion
    4. Fetch full chunk details for top-ranked hits
    5. Populate freshness metadata
    6. Apply token budget and return results
    """
    from datetime import datetime  # noqa: PLC0415

    from repo_intel.security.prompt_guard import (  # noqa: PLC0415
        sanitize_query,
    )

    # 0. Prompt-injection defense
    sanitized = sanitize_query(request.query)
    if not sanitized:
        logger.warning(
            "Search query blocked by prompt-injection guard: %s",
            request.query[:80],
        )
        return []
    if sanitized != request.query:
        logger.info(
            "Search query sanitized by prompt-injection guard"
        )
    effective_query = sanitized

    # 1. Resolve active generations
    generation_ids = await _get_active_generation_ids(session, request.repository_id)

    if not generation_ids:
        logger.warning("No active index generations found for search scope")
        return []

    # 2. Run all four candidate retrieval modes (exact, FTS, vector, symbol)
    exact = await _exact_candidates(
        session, effective_query, request.repository_id, generation_ids,
        exclude_doc_chunks=request.exclude_doc_chunks,
    )
    lexical = await _lexical_candidates(
        session, effective_query, request.repository_id, generation_ids,
        exclude_doc_chunks=request.exclude_doc_chunks,
    )
    semantic = await _semantic_candidates(
        session, effective_query, request.repository_id, generation_ids,
        exclude_doc_chunks=request.exclude_doc_chunks,
    )
    symbol = await _symbol_candidates(
        session, effective_query, request.repository_id, generation_ids,
        exclude_doc_chunks=request.exclude_doc_chunks,
    )

    # 3. Fuse
    fused = _rrf_fuse(
        [exact, lexical, semantic, symbol],
        ["exact", "lexical", "semantic", "symbol"],
    )

    if not fused:
        logger.info("No candidates found for query: %s", effective_query[:80])
        return []

    # 4. Fetch details for top candidates (get 3x limit to allow budget trimming)
    top_chunk_ids = [cid for cid, _score, _methods in fused[: request.limit * 3]]
    details = await _fetch_chunk_details(session, top_chunk_ids)

    # 5. Build results in fusion order, attaching scores and methods
    results: list[SearchResult] = []
    for chunk_id, score, methods in fused:
        if len(results) >= request.limit * 3:
            break
        detail = details.get(chunk_id)
        if detail is None:
            continue
        detail.score = score
        detail.retrieval_methods = methods  # type: ignore[assignment]
        detail.relevance_reason = _build_reason(methods)
        # Default evidence_kind: chunks from hybrid search are exact_source
        if not detail.text:
            detail.evidence_kind = "missing"
        else:
            detail.evidence_kind = "exact_source"
        results.append(detail)

    # 6. Populate freshness metadata and update evidence_kind for stale content
    now = datetime.now(UTC)
    for r in results:
        gid = r.generation_id
        if gid:
            created_at_str = await _get_generation_created_at(session, gid)
            r.generation_created_at = created_at_str
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(
                        created_at_str.replace("Z", "+00:00")
                    )
                    age_seconds = (now - created_at).total_seconds()
                    r.is_stale = age_seconds > _STALE_THRESHOLD_SECONDS
                    # Mark stale content so consumers can distinguish
                    if r.is_stale and r.evidence_kind == "exact_source":
                        r.evidence_kind = "stale"
                except (ValueError, TypeError):
                    r.is_stale = False
        else:
            r.is_stale = False

    # 6a. Deduplicate overlapping chunks from the same file.
    #     When boundary-chunking small files produces multiple chunks that
    #     overlap in line range, keep only the one with the highest score.
    results = _dedup_overlapping_chunks(results)

    # 7. Apply token budget
    results = _apply_token_budget(results, request.token_budget)

    # 8. Apply minimum score filter
    if request.min_score > 0:
        max_score = 4.0 / (_RRF_K + 1)
        results = [
            r for r in results
            if (r.score / max_score if max_score else 0) >= request.min_score
        ]

    # 9. Enforce final limit (dedup and token-budget trimming may have
    #    reduced the count, but never exceed the requested limit).
    results = results[:request.limit]

    return results


def _build_reason(methods: list[str]) -> str:
    """Build a human-readable relevance reason from retrieval methods."""
    if not methods:
        return ""
    method_labels = {
        "exact": "exact identifier/path match",
        "lexical": "full-text keyword match",
        "semantic": "semantic similarity match",
        "symbol": "symbol reference match",
    }
    parts = [method_labels.get(m, m) for m in methods]
    return "Matched by: " + "; ".join(parts)
