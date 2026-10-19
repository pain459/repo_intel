"""SQLAlchemy declarative base and Phase 2 models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Default embedding dimension — nomic-embed-text produces 768-dim vectors.
# The Chunk table column uses this; runtime validation ensures stored vectors match.
DEFAULT_EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    """Shared declarative base for all models."""

    pass


class TimestampMixin:
    """Adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    git_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")
    # Optional include/exclude patterns (JSON)
    include_patterns: Mapped[list] = mapped_column(JSONB, nullable=True)
    exclude_patterns: Mapped[list] = mapped_column(JSONB, nullable=True)

    # Relationships
    files: Mapped[list[FileRecord]] = relationship(
        back_populates="repository", cascade="all, delete-orphan",
    )
    jobs: Mapped[list[IndexJob]] = relationship(back_populates="repository")
    generations: Mapped[list[IndexGeneration]] = relationship(
        back_populates="repository",
    )


# ---------------------------------------------------------------------------
# Index Generations — track embedding model / version per scan
# ---------------------------------------------------------------------------


class IndexGeneration(Base, TimestampMixin):
    __tablename__ = "index_generations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    # State machine: building -> active | failed | retired
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="building")
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Chunker/parser version for reproducibility
    chunker_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # How many chunks in this generation
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    repository: Mapped[Repository] = relationship(back_populates="generations")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="generation")


# ---------------------------------------------------------------------------
# Files — one row per tracked file in a repository
# ---------------------------------------------------------------------------


class FileRecord(Base, TimestampMixin):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("repository_id", "relative_path", name="uq_repo_files_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    git_head: Mapped[str | None] = mapped_column(String(40), nullable=True)
    worktree_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    repository: Mapped[Repository] = relationship(back_populates="files")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="file")


# ---------------------------------------------------------------------------
# Chunks — content + FTS + vector
# ---------------------------------------------------------------------------


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("generation_id", "content_hash", name="uq_gen_chunk_content"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), nullable=False)
    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("index_generations.id"), nullable=False,
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    # "function", "class", "file", "doc"
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False, default="file")
    symbol_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # SHA-256 prefix of the content for dedup
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Actual text (bounded) — stored as TEXT
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Estimated tokens (rough)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pgvector embedding — dimension from config at index time
    embedding: Mapped[list[float] | None] = mapped_column(Vector, nullable=True)
    # True when this chunk belongs to a generation that is no longer active
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    file: Mapped[FileRecord] = relationship(back_populates="chunks")
    generation: Mapped[IndexGeneration] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# Symbols — definitions discovered during parsing
# ---------------------------------------------------------------------------


class Symbol(Base, TimestampMixin):
    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    fully_qualified: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # enum: function, class, method, variable, interface, enum, type_alias
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Line range where defined
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_source: Mapped[str] = mapped_column(String(64), nullable=False, default="text")
    generation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("index_generations.id"), nullable=False,
    )


# ---------------------------------------------------------------------------
# Index Jobs — background work queue
# ---------------------------------------------------------------------------


class IndexJob(Base, TimestampMixin):
    __tablename__ = "index_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    # initial_scan | incremental | refresh | delete
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # pending | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dedup key to avoid duplicate jobs
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="jobs")


# ---------------------------------------------------------------------------
# Retrieval Events — observability for search queries
# ---------------------------------------------------------------------------


class RetrievalEvent(Base, TimestampMixin):
    __tablename__ = "retrieval_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repositories.id"), nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    num_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_tokens_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Which index generation served this query
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    # Selected chunk IDs for audit trail
    selected_chunk_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # How many stale chunks appeared in results
    stale_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Memories — evidence-backed decisions (Phase 4 schema, Phase 3 tables)
# ---------------------------------------------------------------------------


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repositories.id"), nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    # candidate | verified | superseded | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Who/what created this memory (agent session, user CLI, etc.)
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # When to re-evaluate this memory
    expiry_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


# ---------------------------------------------------------------------------
# Task Checkpoints — session state snapshots
# ---------------------------------------------------------------------------


class TaskCheckpoint(Base):
    __tablename__ = "task_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("repositories.id"), nullable=True,
    )
    session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    current_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pending_steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
