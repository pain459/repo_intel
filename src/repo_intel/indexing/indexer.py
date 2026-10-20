"""Indexer: orchestrates file discovery, chunking, embedding, and DB upsert."""

from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from repo_intel.db.models import (
    Chunk,
    FileRecord,
    IndexGeneration,
    IndexJob,
    Repository,
    Symbol,
    SymbolEdge,
)
from repo_intel.indexing.chunker import chunk_file
from repo_intel.indexing.edge_detector import detect_edges
from repo_intel.indexing.discovery import discover_files
from repo_intel.indexing.embeddings.adapter import get_embeddings_batch
from repo_intel.security.redaction import redact_content

logger = logging.getLogger(__name__)

_MAX_EXC_MSG_LEN = 512


def _safe_exc_msg(exc: Exception) -> str:
    """Return a short, safe version of an exception message.

    SQLAlchemy / psycopg exceptions embed full parameter dicts that contain
    chunk content.  Strip those out so they never leak into logs.
    """
    msg = str(exc)
    # Strip the [parameters: ...] and [SQL: ...] blocks that SQLAlchemy appends
    # and that contain embedding/chunk payloads.
    for marker in ("[SQL:", "[parameters:"):
        idx = msg.find(marker)
        if idx >= 0:
            msg = msg[:idx].rstrip()
            break
    if len(msg) > _MAX_EXC_MSG_LEN:
        msg = msg[:_MAX_EXC_MSG_LEN] + "…"
    return msg


# ---------------------------------------------------------------------------
# Repository scanning
# ---------------------------------------------------------------------------


async def scan_repository(
    session: AsyncSession,
    repo_id: uuid.UUID,
    job_id: uuid.UUID,
) -> int:
    """Full scan of a repository: discover files, chunk, embed, upsert.

    Returns the number of chunks indexed.
    """
    settings = __import__("repo_intel.config", fromlist=["get_settings"]).get_settings()

    # 1. Load repository
    repo_stmt = select(Repository).where(Repository.id == repo_id)
    repo = (await session.scalars(repo_stmt)).first()
    if not repo:
        raise ValueError(f"Repository {repo_id} not found")

    # 2. Create an index generation
    generation = IndexGeneration(
        repository_id=repo_id,
        state="building",
        embedding_model=settings.embedding_model,
        embedding_dimension=768,  # nomic-embed-text
        chunker_version="1.0.0",  # current chunker version for reproducibility
    )
    session.add(generation)
    await session.flush()
    generation_id = generation.id

    # 3. Discover files
    discovered = discover_files(repo.git_path)
    logger.info("Discovered %d files in %s", len(discovered), repo.git_path)

    if not discovered:
        generation.state = "active"
        # Mark job complete
        await _complete_job(session, job_id)
        return 0

    # 4. Read content, chunk, and prepare upserts
    total_chunks = 0
    file_ids: dict[str, uuid.UUID] = {}  # relative_path -> existing file_id
    # Collect chunk objects for embedding after DB flush
    pending_chunks: list[tuple[Chunk, str]] = []  # (chunk_rec, content_text)
    # Track content hashes across all files to prevent
    # uq_gen_chunk_content violations when identical content
    # appears in different files (e.g., generated boilerplate).
    seen_hashes: set[str] = set()

    # Collect per-file data for edge detection (run after symbols flushed)
    file_edge_data: dict[str, tuple[str, set[str]]] = {}  # path -> (content, defined_symbols)

    # Load existing files for this repo (for incremental diff).
    # Include soft-deleted rows so that files reappearing on disk are
    # reused rather than re-inserted (which would hit uq_repo_files_path).
    existing_stmt = select(FileRecord).where(
        FileRecord.repository_id == repo_id,
    )
    existing_files = {f.relative_path: f for f in await session.scalars(existing_stmt)}

    # Track which files we see this scan
    seen_paths: set[str] = set()
    # Track file_ids that were unchanged and reused from a prior generation.
    # Their chunks should NOT be marked stale during the old-gen cleanup.
    unchanged_file_ids: set[uuid.UUID] = set()

    for df in discovered:
        seen_paths.add(df.relative_path)

        # Check if file content changed
        existing = existing_files.get(df.relative_path)
        file_changed = True
        if existing and existing.content_hash == df.content_hash and not existing.worktree_dirty:
            # No change, keep existing chunks from prior generation.
            # Reinstate if it was soft-deleted by a previous generation
            existing.deleted = False
            file_ids[df.relative_path] = existing.id
            unchanged_file_ids.add(existing.id)
            file_changed = False

        # Read file content (needed for edge detection even when unchanged)
        import os
        file_path = os.path.join(repo.git_path, df.relative_path)
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", df.relative_path, exc)
            continue

        # Chunk the content to derive symbols (always needed for edge
        # detection, even when file unchanged).  For unchanged files we
        # skip DB writes but still need symbol names.
        chunks = chunk_file(df.relative_path, content)

        # Extract symbol names from chunks for edge detection
        file_symbols: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_type in ("function", "class", "method") and chunk.symbol_name:
                file_symbols.add(chunk.symbol_name)

        # Upsert DB records only when file actually changed
        if file_changed:
            if not chunks:
                file_edge_data[df.relative_path] = (content, file_symbols)
                continue

            # Upsert file record
            if existing and existing.content_hash != df.content_hash:
                existing.content_hash = df.content_hash
                existing.size_bytes = df.size_bytes
                existing.language = df.language
                # Reinstate if it was soft-deleted by a previous generation
                existing.deleted = False
            elif existing:
                # Reinstate soft-deleted rows that still exist on disk
                existing.deleted = False
                file_edge_data[df.relative_path] = (content, file_symbols)
                continue

            if existing:
                file_id = existing.id
            else:
                file_rec = FileRecord(
                    repository_id=repo_id,
                    relative_path=df.relative_path,
                    language=df.language,
                    size_bytes=df.size_bytes,
                    content_hash=df.content_hash,
                )
                session.add(file_rec)
                await session.flush()
                file_id = file_rec.id

            # Upsert chunks (embedding set later in batch)
            for chunk in chunks:
                # Redact secrets from chunk content before storage
                redacted = redact_content(chunk.content)
                final_content = redacted.cleaned_text
                if redacted.patterns_matched > 0:
                    logger.warning(
                        "Redacted %d secret pattern(s) in %s:%d-%d: %s",
                        redacted.patterns_matched,
                        df.relative_path,
                        chunk.start_line,
                        chunk.end_line,
                        ", ".join(set(redacted.pattern_labels)),
                    )
                chunk_rec = Chunk(
                    file_id=file_id,
                    generation_id=generation_id,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    chunk_type=chunk.chunk_type,
                    symbol_name=chunk.symbol_name,
                    content_hash=chunk.content_hash,
                    content=final_content,
                    estimated_tokens=chunk.estimated_tokens,
                    embedding=None,  # filled in batch below
                )
                if chunk.content_hash in seen_hashes:
                    # Duplicate content — skip to avoid UniqueViolation.
                    # The first chunk with this content already carries
                    # the symbol_name and file association.
                    continue
                seen_hashes.add(chunk.content_hash)
                session.add(chunk_rec)
                pending_chunks.append((chunk_rec, final_content))
                total_chunks += 1

        # Detect symbols (functions, classes) from chunks and persist them
        # for the new generation (needed for edge resolution, even unchanged)
        if existing:
            file_id = existing.id
        else:
            file_id = file_ids.get(df.relative_path)

        for chunk in chunks:
            if chunk.chunk_type in ("function", "class", "method") and chunk.symbol_name:
                if file_id is None:
                    continue
                symbol = Symbol(
                    file_id=file_id,
                    name=chunk.symbol_name,
                    kind=chunk.chunk_type,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    parser_source="text",
                    generation_id=generation_id,
                )
                session.add(symbol)

        # Store content + defined symbols for edge detection (batched later)
        # Done for every file, even unchanged ones, so edges are always current
        file_edge_data[df.relative_path] = (content, file_symbols)

    # 4b. Flush so that Symbol rows acquire IDs for edge resolution
    if pending_chunks:
        await session.flush()
        logger.info(
            "Generating embeddings for %d chunks (batch_size=%d)",
            len(pending_chunks),
            settings.embedding_batch_size,
        )
        chunk_texts = [content for _, content in pending_chunks]
        embeddings = await get_embeddings_batch(chunk_texts)
        for i, (chunk_rec, _content) in enumerate(pending_chunks):
            if i < len(embeddings) and embeddings[i] is not None:
                chunk_rec.embedding = embeddings[i]
            else:
                logger.debug("Embedding unavailable for chunk %s", chunk_rec.id)

    # 4c. Detect and persist symbol dependency edges
    # First, remove edges from older generations to avoid hitting
    # uq_symbol_edge (which lacks generation_id).
    await session.execute(
        sa_delete(SymbolEdge).where(
            SymbolEdge.repository_id == repo_id,
            SymbolEdge.generation_id != generation_id,
        )
    )

    # Build a global set of defined symbol names for cross-file resolution
    all_defined_symbols: set[str] = set()
    for (_, file_syms) in file_edge_data.values():
        all_defined_symbols.update(file_syms)

    # Flush symbols so they have IDs
    await session.flush()

    # Build symbol name -> list of (file_id, symbol_id) mappings
    symbol_rows = await session.execute(
        select(Symbol).where(
            Symbol.generation_id == generation_id,
        )
    )
    symbol_map: dict[str, list[uuid.UUID]] = {}
    for sym in symbol_rows.scalars():
        symbol_map.setdefault(sym.name, []).append(sym.id)

    # Deduplicate edges across files: uq_symbol_edge lacks generation_id
    seen_edges: set[tuple[uuid.UUID, uuid.UUID, str]] = set()

    for rel_path, (file_content, file_syms) in file_edge_data.items():
        raw_edges = detect_edges(file_content, all_defined_symbols)
        if not raw_edges:
            continue
        for edge in raw_edges:
            # Resolve from/to symbol names to IDs
            from_ids = symbol_map.get(edge.from_name, [])
            to_ids = symbol_map.get(edge.to_name, [])
            if not from_ids or not to_ids:
                continue
            # Use the first matching symbol ID;
            # for same-name symbols in different files this is an approximation
            edge_key = (from_ids[0], to_ids[0], edge.relation_type)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            session.add(
                SymbolEdge(
                    repository_id=repo_id,
                    from_symbol_id=from_ids[0],
                    to_symbol_id=to_ids[0],
                    relation_type=edge.relation_type,
                    evidence_location=f"{rel_path}:{edge.line}",
                    confidence=0.7,
                    generation_id=generation_id,
                )
            )

    # 5. Mark deleted files
    for rel_path, existing in existing_files.items():
        if rel_path not in seen_paths:
            existing.deleted = True

    # 5a. Deactivate older generations so that only one generation
    #     is active per repository at any time.
    await session.execute(
        update(IndexGeneration)
        .where(
            IndexGeneration.repository_id == repo_id,
            IndexGeneration.state == "active",
            IndexGeneration.id != generation_id,
        )
        .values(state="retired")
    )

    # 5b. Reassign unchanged file chunks to the new generation so that
    #     search (which filters by active generation_id) can find them.
    #     Then mark remaining old-gen chunks as stale.
    stale_exclude: list[uuid.UUID] = list(unchanged_file_ids)
    if stale_exclude:
        # First, update generation_id for unchanged file chunks
        await session.execute(
            update(Chunk)
            .where(
                Chunk.file_id.in_(stale_exclude),
                Chunk.generation_id != generation_id,
            )
            .values(generation_id=generation_id)
        )
        # Mark old-gen chunks (except unchanged) as stale
        await session.execute(
            update(Chunk)
            .where(
                Chunk.file_id.in_(
                    select(FileRecord.id).where(
                        FileRecord.repository_id == repo_id,
                    ),
                ),
                Chunk.generation_id != generation_id,
                Chunk.stale == False,  # noqa: E712
            )
            .values(stale=True)
        )
    else:
        # No unchanged files — mark all old-gen chunks stale
        await session.execute(
            update(Chunk)
            .where(
                Chunk.file_id.in_(
                    select(FileRecord.id).where(
                        FileRecord.repository_id == repo_id,
                    ),
                ),
                Chunk.generation_id != generation_id,
                Chunk.stale == False,  # noqa: E712
            )
            .values(stale=True)
        )

    # 6. Update generation state
    generation.chunk_count = total_chunks
    generation.state = "active"

    await _complete_job(session, job_id)

    logger.info("Indexed %d chunks for repo %s", total_chunks, repo.name)
    return total_chunks


# ---------------------------------------------------------------------------
# Incremental scan (check for changes since last index)
# ---------------------------------------------------------------------------


async def incremental_scan(
    session: AsyncSession,
    repo_id: uuid.UUID,
) -> bool:
    """Check if any files have changed and trigger a re-index if so.

    Returns True if re-index was triggered.
    """
    repo_stmt = select(Repository).where(Repository.id == repo_id)
    repo = (await session.scalars(repo_stmt)).first()
    if not repo:
        return False

    # Check active generation
    gen_stmt = (
        select(IndexGeneration)
        .where(
            IndexGeneration.repository_id == repo_id,
            IndexGeneration.state == "active",
        )
        .order_by(IndexGeneration.created_at.desc())
        .limit(1)
    )
    active_gen = (await session.scalars(gen_stmt)).first()

    if not active_gen:
        # No index yet, trigger full scan
        await _enqueue_initial_scan(session, repo_id)
        return True

    # Compare discovered files against indexed files
    discovered = discover_files(repo.git_path)
    existing_stmt = select(FileRecord).where(
        FileRecord.repository_id == repo_id,
        FileRecord.deleted == False,  # noqa: E712
    )
    existing = {f.relative_path: f for f in await session.scalars(existing_stmt)}

    changed = False
    seen_paths: set[str] = set()
    for df in discovered:
        seen_paths.add(df.relative_path)
        ex = existing.get(df.relative_path)
        if ex:
            # Check content hash
            import os
            file_path = os.path.join(repo.git_path, df.relative_path)
            try:
                with open(file_path, "rb") as f:
                    new_hash = hashlib.sha256(f.read()).hexdigest()
                if new_hash != ex.content_hash:
                    changed = True
                    break
            except OSError:
                pass
        else:
            # New file
            changed = True
            break

    if not changed:
        # Check for deleted files
        for rel_path in existing:
            if rel_path not in seen_paths:
                changed = True
                break

    if changed:
        await _enqueue_initial_scan(session, repo_id)

    return changed


# ---------------------------------------------------------------------------
# Job management helpers
# ---------------------------------------------------------------------------


async def _enqueue_initial_scan(session: AsyncSession, repo_id: uuid.UUID) -> None:
    """Create an index job for an initial full scan."""
    job = IndexJob(
        repository_id=repo_id,
        job_type="initial_scan",
        status="pending",
    )
    session.add(job)
    await session.flush()


async def _complete_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    """Mark an index job as completed."""
    await session.execute(
        update(IndexJob)
        .where(IndexJob.id == job_id, IndexJob.status == "running")
        .values(status="completed", updated_at=__import__("sqlalchemy").func.now())
    )


async def _fail_job(session: AsyncSession, job_id: uuid.UUID, error: str) -> None:
    """Mark an index job as failed."""
    await session.execute(
        update(IndexJob)
        .where(IndexJob.id == job_id)
        .values(
            status="failed",
            error_summary=error,
            attempts=IndexJob.attempts + 1,
            updated_at=__import__("sqlalchemy").func.now(),
        )
    )


# ---------------------------------------------------------------------------
# Worker polling loop
# ---------------------------------------------------------------------------


async def worker_tick(session: AsyncSession) -> None:
    """One tick of the indexing worker: pick pending jobs, run them."""
    # Find pending jobs
    pending_stmt = (
        select(IndexJob)
        .where(IndexJob.status == "pending")
        .order_by(IndexJob.created_at)
        .limit(5)
    )
    jobs = list(await session.scalars(pending_stmt))

    for job in jobs:
        # Capture scalar fields before potentially mutating them,
        # so exception logging never touches stale ORM objects
        _job_id = job.id
        _repo_id = job.repository_id

        # Mark running
        await session.execute(
            update(IndexJob)
            .where(IndexJob.id == _job_id)
            .values(status="running")
        )

        try:
            if job.job_type == "initial_scan":
                await scan_repository(session, _repo_id, _job_id)
            else:
                logger.warning("Unknown job type %s, skipping", job.job_type)
                await _fail_job(session, _job_id, f"Unknown job type: {job.job_type}")
        except Exception as exc:
            safe_msg = _safe_exc_msg(exc)
            logger.error("Job %s: failed - %s", _job_id, safe_msg)
            # Flush errors (e.g. constraint violations) leave the session in
            # a PendingRollbackError state.  Roll back so we can still mark
            # the job as failed.
            await session.rollback()
            try:
                await _fail_job(session, _job_id, safe_msg)
            except Exception:
                logger.error(
                    "Job %s: session unusable; aborting remaining ticks",
                    _job_id,
                )
                raise
