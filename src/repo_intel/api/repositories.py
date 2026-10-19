"""REST API for repository management and indexing."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RepositoryCreate(BaseModel):
    path: str
    name: str | None = None


class RepositoryOut(BaseModel):
    id: uuid.UUID
    name: str
    git_path: str
    status: str
    chunk_count: int = 0
    file_count: int = 0

    model_config = {"from_attributes": True}


class IndexTriggerOut(BaseModel):
    job_id: uuid.UUID
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=IndexTriggerOut, status_code=201)
async def register_repository(body: RepositoryCreate) -> IndexTriggerOut:
    """Register a new repository and queue an initial scan."""
    import os  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import IndexJob, Repository
    from repo_intel.db.session import get_session_factory

    resolved = os.path.abspath(body.path)
    if not os.path.isdir(resolved):
        raise HTTPException(400, f"Not a directory: {resolved}")

    repo_name = body.name or os.path.basename(resolved)

    async with get_session_factory()() as session:
        # Check duplicate
        stmt = select(Repository).where(Repository.git_path == resolved)
        existing = (await session.scalars(stmt)).first()
        if existing:
            return IndexTriggerOut(
                job_id=existing.id,
                message=f"Already registered: {existing.name}",
            )

        repo = Repository(
            id=uuid.uuid4(),
            name=repo_name,
            git_path=resolved,
            status="registered",
        )
        session.add(repo)

        job = IndexJob(
            repository_id=repo.id,
            job_type="initial_scan",
            status="pending",
        )
        session.add(job)
        await session.commit()

    return IndexTriggerOut(
        job_id=job.id,
        message=f"Registered {repo_name} → {resolved}",
    )


@router.get("/", response_model=list[RepositoryOut])
async def list_repositories() -> list[RepositoryOut]:
    """List all registered repositories with index status."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, IndexGeneration, Repository
    from repo_intel.db.session import get_session_factory

    async with get_session_factory()() as session:
        repos = await session.scalars(
            select(Repository).order_by(Repository.name)
        )
        repos = list(repos)

        results: list[RepositoryOut] = []
        for repo in repos:
            # Active generation chunk count
            gen_stmt = (
                select(IndexGeneration)
                .where(
                    IndexGeneration.repository_id == repo.id,
                    IndexGeneration.state == "active",
                )
                .order_by(IndexGeneration.created_at.desc())
                .limit(1)
            )
            gen = (await session.scalars(gen_stmt)).first()
            chunk_count = gen.chunk_count if gen else 0

            # File count
            file_count = (
                await session.scalar(
                    select(func.count()).select_from(FileRecord).where(
                        FileRecord.repository_id == repo.id,
                        FileRecord.deleted == False,  # noqa: E712
                    )
                )
            ) or 0

            results.append(
                RepositoryOut(
                    id=repo.id,
                    name=repo.name,
                    git_path=repo.git_path,
                    status=repo.status,
                    chunk_count=chunk_count,
                    file_count=file_count,
                )
            )

    return results


@router.get("/{repo_id}", response_model=RepositoryOut)
async def get_repository(repo_id: uuid.UUID) -> RepositoryOut:
    """Get details for a single repository."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from repo_intel.db.models import FileRecord, IndexGeneration, Repository
    from repo_intel.db.session import get_session_factory

    async with get_session_factory()() as session:
        repo = (
            await session.scalars(
                select(Repository).where(Repository.id == repo_id)
            )
        ).first()
        if not repo:
            raise HTTPException(404, "Repository not found")

        gen_stmt = (
            select(IndexGeneration)
            .where(
                IndexGeneration.repository_id == repo.id,
                IndexGeneration.state == "active",
            )
            .order_by(IndexGeneration.created_at.desc())
            .limit(1)
        )
        gen = (await session.scalars(gen_stmt)).first()
        chunk_count = gen.chunk_count if gen else 0

        file_count = (
            await session.scalar(
                select(func.count()).select_from(FileRecord).where(
                    FileRecord.repository_id == repo.id,
                    FileRecord.deleted == False,  # noqa: E712
                )
            )
        ) or 0

    return RepositoryOut(
        id=repo.id,
        name=repo.name,
        git_path=repo.git_path,
        status=repo.status,
        chunk_count=chunk_count,
        file_count=file_count,
    )


@router.post("/{repo_id}/index", response_model=IndexTriggerOut)
async def trigger_index(repo_id: uuid.UUID) -> IndexTriggerOut:
    """Trigger an immediate re-index of a repository."""
    from sqlalchemy import select  # noqa: PLC0415

    from repo_intel.db.models import IndexJob, Repository
    from repo_intel.db.session import get_session_factory

    async with get_session_factory()() as session:
        repo = (
            await session.scalars(
                select(Repository).where(Repository.id == repo_id)
            )
        ).first()
        if not repo:
            raise HTTPException(404, "Repository not found")

        job = IndexJob(
            repository_id=repo_id,
            job_type="initial_scan",
            status="pending",
        )
        session.add(job)
        await session.commit()

    return IndexTriggerOut(
        job_id=job.id,
        message=f"Re-index job queued for {repo.name}",
    )
