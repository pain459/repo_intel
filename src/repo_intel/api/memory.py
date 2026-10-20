"""Memory CRUD: read/write persistent agent memories."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from repo_intel.db.models import Memory, Repository
from repo_intel.db.session import get_session_factory

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MemoryCreate(BaseModel):
    repository_id: uuid.UUID | None = Field(
        None, description="Scope to a repository (global if omitted)"
    )
    kind: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Memory kind: preference, observation, pattern, instruction, etc.",
    )
    statement: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The memory content",
    )
    evidence: dict[str, Any] | None = Field(
        None, description="Supporting evidence or metadata"
    )
    source_commit: str | None = Field(
        None, description="Git commit hash that prompted this memory"
    )
    author: str | None = Field(
        None, description="Creator: session ID, agent name, or user"
    )
    expiry_time: str | None = Field(
        None,
        description="ISO-8601 timestamp after which the memory should be re-evaluated",
    )


class MemoryOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID | None
    kind: str
    statement: str
    status: str
    evidence: dict[str, Any] | None
    source_commit: str | None
    author: str | None
    created_at: str
    relevance_score: float = 0.0


class MemoryListRequest(BaseModel):
    repository_id: uuid.UUID | None = Field(None)
    kind: str | None = Field(None, description="Filter by kind")
    status: str | None = Field(None, description="Filter by status")
    query: str | None = Field(None, description="FTS search on statement")
    limit: int = Field(20, ge=1, le=200)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=MemoryOut, status_code=201)
async def create_memory(body: MemoryCreate) -> MemoryOut:
    """Create a new agent memory."""
    if body.repository_id:
        _validate_repo(body.repository_id)

    factory = get_session_factory()
    async with factory() as session:
        memory = Memory(
            repository_id=body.repository_id,
            kind=body.kind,
            statement=body.statement,
            status="candidate",
            evidence=body.evidence,
            source_commit=body.source_commit,
            author=body.author,
            expiry_time=body.expiry_time,
        )
        session.add(memory)
        await session.commit()
        await session.refresh(memory)

    return _to_out(memory)


@router.get("/", response_model=list[MemoryOut])
async def list_memories(
    repository_id: uuid.UUID | None = None,
    kind: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> list[MemoryOut]:
    """List memories, optionally filtered and scored by relevance."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Memory)
        if repository_id:
            stmt = stmt.where(Memory.repository_id == repository_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        if status:
            stmt = stmt.where(Memory.status == status)

        rows = await session.scalars(
            stmt.order_by(Memory.id.desc()).limit(limit)
        )
        memories = list(rows)

    # Apply FTS scoring if query provided
    if query and memories:
        memories = await _score_by_relevance(memories, query)

    return [_to_out(m) for m in memories]


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: uuid.UUID,
    body: dict[str, Any],
) -> MemoryOut:
    """Update a memory (status, statement, etc.)."""
    factory = get_session_factory()
    async with factory() as session:
        memory = (
            await session.scalars(
                select(Memory).where(Memory.id == memory_id)
            )
        ).first()
        if not memory:
            raise HTTPException(404, f"Memory {memory_id} not found")

        allowed = {"status", "statement", "evidence", "kind"}
        for key, value in body.items():
            if key in allowed and hasattr(memory, key):
                setattr(memory, key, value)

        await session.commit()
        await session.refresh(memory)

    return _to_out(memory)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID) -> None:
    """Delete a memory."""
    factory = get_session_factory()
    async with factory() as session:
        memory = (
            await session.scalars(
                select(Memory).where(Memory.id == memory_id)
            )
        ).first()
        if not memory:
            raise HTTPException(404, f"Memory {memory_id} not found")
        await session.delete(memory)
        await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _score_by_relevance(
    memories: list[Memory],
    query: str,
) -> list[Memory]:
    """Score memories by FTS relevance to the query, in-memory fallback."""
    # Quick text-match scoring as fallback when FTS on memories table
    # isn't indexed yet
    query_lower = query.lower()
    scored: list[tuple[float, Memory]] = []
    for m in memories:
        score = 0.0
        stmt_lower = m.statement.lower()
        if query_lower in stmt_lower:
            score += 1.0
        for word in query_lower.split():
            if word in stmt_lower:
                score += 0.5
        # Boost verified memories
        if m.status == "verified":
            score += 0.3
        scored.append((score, m))
    scored.sort(key=lambda p: -p[0])
    return [m for _, m in scored]


def _to_out(m: Memory) -> MemoryOut:
    return MemoryOut(
        id=m.id,
        repository_id=m.repository_id,
        kind=m.kind,
        statement=m.statement,
        status=m.status,
        evidence=m.evidence,
        source_commit=m.source_commit,
        author=m.author,
        created_at=str(m.created_at)
        if hasattr(m, "created_at") and m.created_at
        else "",
    )


async def _validate_repo(repo_id: uuid.UUID) -> None:
    """Raise 404 if repository doesn't exist."""
    factory = get_session_factory()
    async with factory() as session:
        repo = (
            await session.scalars(
                select(Repository).where(Repository.id == repo_id)
            )
        ).first()
        if not repo:
            raise HTTPException(404, f"Repository {repo_id} not found")
