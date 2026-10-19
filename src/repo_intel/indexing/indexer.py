"""Indexer: orchestrates file discovery, chunking, embedding, and DB upsert."""

from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from repo_intel.config import get_settings
from repo_intel.db.models import (
    Chunk,
    FileRecord,
    IndexGeneration,
    IndexJob,
    Repository,
    Symbol,
)
from repo_intel.indexing.chunker import chunk_file
from repo_intel.indexing.discovery import discover_files
from repo_intel.indexing.embeddings.adapter import get_embeddings_batch

logger = logging.getLogger(__name__)


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
    )
    session.add(generation)
    await session.flush()
    generation_id = generation.id

    # 3. Discover files
    discovered = discover_files(repo.git_path)
    logger.info("Discovered %d files in %s", len(discovered), repo.git_path)

    if not discovered:
        generation.state = "active"
        await session.commit()
        # Mark job complete
        await _complete_job(session, job_id)
        return 0

    # 4. Read content, chunk, and prepare upserts
    total_chunks = 0
    file_ids: dict[str, uuid.UUID] = {}  # relative_path -> existing file_id
    # Collect chunk objects for embedding after DB flush
    pending_chunks: list[tuple[Chunk, str]] = []  # (chunk_rec, content_text)

    # Load existing files for this repo (for incremental diff)
    existing_stmt = select(FileRecord).where(
        FileRecord.repository_id == repo_id,
        FileRecord.deleted == False,  # noqa: E712
    )
    existing_files = {f.relative_path: f for f in await session.scalars(existing_stmt)}

    # Track which files we see this scan
    seen_paths: set[str] = set()

    for df in discovered:
        seen_paths.add(df.relative_path)

        # Check if file content changed
        existing = existing_files.get(df.relative_path)
        if existing and existing.content_hash == df.content_hash and not existing.worktree_dirty:
            # No change, keep existing chunks
            file_ids[df.relative_path] = existing.id
            continue

        # Read file content
        import os
        file_path = os.path.join(repo.git_path, df.relative_path)
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", df.relative_path, exc)
            continue

        # Chunk the content
        chunks = chunk_file(df.relative_path, content)
        if not chunks:
            continue

        # Upsert file record
        if existing and existing.content_hash != df.content_hash:
            existing.content_hash = df.content_hash
            existing.size_bytes = df.size_bytes
            existing.language = df.language
        elif existing:
            file_ids[df.relative_path] = existing.id
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
            chunk_rec = Chunk(
                file_id=file_id,
                generation_id=generation_id,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                chunk_type=chunk.chunk_type,
                symbol_name=chunk.symbol_name,
                content_hash=chunk.content_hash,
                content=chunk.content,
                estimated_tokens=chunk.estimated_tokens,
                embedding=None,  # filled in batch below
            )
            session.add(chunk_rec)
            pending_chunks.append((chunk_rec, chunk.content))
            total_chunks += 1

        # Detect symbols (functions, classes) from chunks
        for chunk in chunks:
            if chunk.chunk_type in ("function", "class", "method") and chunk.symbol_name:
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

    # 4b. Flush chunk records, then generate embeddings in batch
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

    # 5. Mark deleted files
    for rel_path, existing in existing_files.items():
        if rel_path not in seen_paths:
            existing.deleted = True

    # 6. Update generation state
    generation.chunk_count = total_chunks
    generation.state = "active"

    await session.commit()
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
        # Mark running
        await session.execute(
            update(IndexJob)
            .where(IndexJob.id == job.id)
            .values(status="running")
        )

        try:
            if job.job_type == "initial_scan":
                await scan_repository(session, job.repository_id, job.id)
            else:
                logger.warning("Unknown job type %s, skipping", job.job_type)
                await _fail_job(session, job.id, f"Unknown job type: {job.job_type}")
        except Exception as exc:
            logger.exception("Job %s failed: %s", job.id, exc)
            await _fail_job(session, job.id, str(exc))
            await session.commit()
