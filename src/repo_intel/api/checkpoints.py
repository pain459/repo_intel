"""Checkpoint CRUD: save/restore agent session state."""

from __future__ import annotations

import uuid

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repo_intel.db.session import get_session_factory
from sqlalchemy import select

from repo_intel.db.models import Memory, Repository, TaskCheckpoint

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CheckpointCreate(BaseModel):
    repository_id: uuid.UUID | None = Field(
        None, description="Scope to a repository"
    )
    session_id: str | None = Field(
        None, description="Session identifier for grouping"
    )
    objective: str = Field(..., min_length=1, max_length=4096)
    current_state: str | None = Field(None)
    changed_files: list[str] | None = Field(None)
    pending_steps: list[str] | None = Field(None)
    evidence: dict[str, Any] | None = Field(None)


class CheckpointOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID | None
    session_id: str | None
    objective: str
    current_state: str | None
    changed_files: list[str] | None
    pending_steps: list[str] | None
    evidence: dict[str, Any] | None
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=CheckpointOut, status_code=201)
async def create_checkpoint(body: CheckpointCreate) -> CheckpointOut:
    """Save a task checkpoint."""
    if body.repository_id:
        await _validate_repo(body.repository_id)

    factory = get_session_factory()
    async with factory() as session:
        cp = TaskCheckpoint(
            repository_id=body.repository_id,
            session_id=body.session_id,
            objective=body.objective,
            current_state=body.current_state,
            changed_files=body.changed_files,
            pending_steps=body.pending_steps,
            evidence=body.evidence,
        )
        session.add(cp)
        await session.commit()
        await session.refresh(cp)

    return _to_out(cp)


@router.get("/", response_model=list[CheckpointOut])
async def list_checkpoints(
    repository_id: uuid.UUID | None = None,
    session_id: str | None = None,
    limit: int = 20,
) -> list[CheckpointOut]:
    """List checkpoints, most recent first."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(TaskCheckpoint)
        if repository_id:
            stmt = stmt.where(TaskCheckpoint.repository_id == repository_id)
        if session_id:
            stmt = stmt.where(TaskCheckpoint.session_id == session_id)
        rows = await session.scalars(
            stmt.order_by(TaskCheckpoint.created_at.desc()).limit(limit)
        )
    return [_to_out(cp) for cp in rows]


@router.get("/{checkpoint_id}", response_model=CheckpointOut)
async def get_checkpoint(checkpoint_id: uuid.UUID) -> CheckpointOut:
    """Get a single checkpoint."""
    factory = get_session_factory()
    async with factory() as session:
        cp = (
            await session.scalars(
                select(TaskCheckpoint).where(
                    TaskCheckpoint.id == checkpoint_id
                )
            )
        ).first()
        if not cp:
            raise HTTPException(404, f"Checkpoint {checkpoint_id} not found")
    return _to_out(cp)


@router.delete("/{checkpoint_id}", status_code=204)
async def delete_checkpoint(checkpoint_id: uuid.UUID) -> None:
    """Delete a checkpoint."""
    factory = get_session_factory()
    async with factory() as session:
        cp = (
            await session.scalars(
                select(TaskCheckpoint).where(
                    TaskCheckpoint.id == checkpoint_id
                )
            )
        ).first()
        if not cp:
            raise HTTPException(404, f"Checkpoint {checkpoint_id} not found")
        await session.delete(cp)
        await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(cp: TaskCheckpoint) -> CheckpointOut:
    return CheckpointOut(
        id=cp.id,
        repository_id=cp.repository_id,
        session_id=cp.session_id,
        objective=cp.objective,
        current_state=cp.current_state,
        changed_files=cp.changed_files,
        pending_steps=cp.pending_steps,
        evidence=cp.evidence,
        created_at=str(cp.created_at),
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
