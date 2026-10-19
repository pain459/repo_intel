"""Add FTS and vector indexes, retrieval events table.

Revision ID: 003_phase3
Revises: 002_phase2
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "003_phase3"
down_revision: Union[str, None] = "002_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------
    # 1. GIN index on chunks.content for PostgreSQL FTS
    # ----------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_content_gin "
        "ON chunks USING GIN (to_tsvector('english', content))"
    )

    # ----------------------------------------------------------
    # 2. HNSW index on chunks.embedding for cosine vector search
    # ----------------------------------------------------------
    # Only create if there are rows with non-null embeddings
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # ----------------------------------------------------------
    # 3. Index on chunks(generation_id, embedding IS NULL)
    #    for efficient vector-only queries
    # ----------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_gen_embedding "
        "ON chunks (generation_id) WHERE embedding IS NOT NULL"
    )

    # ----------------------------------------------------------
    # 4. Retrieval events table (observability)
    # ----------------------------------------------------------
    op.create_table(
        "retrieval_events",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("repository_id", sa.UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("num_results", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("token_budget", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("estimated_tokens_returned", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ----------------------------------------------------------
    # 5. Memory tables (prep for Phase 4 but created now for schema stability)
    # ----------------------------------------------------------
    op.create_table(
        "memories",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("repository_id", sa.UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'candidate'::character varying")),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("source_commit", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_memories_repo_status", "memories", ["repository_id", "status"])

    op.create_table(
        "task_checkpoints",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("repository_id", sa.UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("session_id", sa.String(256), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("current_state", sa.Text(), nullable=True),
        sa.Column("changed_files", JSONB, nullable=True),
        sa.Column("pending_steps", JSONB, nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_checkpoints_repo_session", "task_checkpoints", ["repository_id", "session_id"])


def downgrade() -> None:
    op.drop_index("idx_checkpoints_repo_session", table_name="task_checkpoints")
    op.drop_table("task_checkpoints")
    op.drop_index("idx_memories_repo_status", table_name="memories")
    op.drop_table("memories")
    op.drop_table("retrieval_events")
    op.drop_index("idx_chunks_gen_embedding", table_name="chunks")
    op.drop_index("idx_chunks_embedding_hnsw", table_name="chunks")
    op.drop_index("idx_chunks_content_gin", table_name="chunks")
