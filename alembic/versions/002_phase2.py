"""phase 2 data model

Revision ID: 002_phase2
Revises: 001_initial
Create Date: 2025-01-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002_phase2'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS repositories (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                git_path VARCHAR(1024) NOT NULL UNIQUE,
                status VARCHAR(32) NOT NULL DEFAULT 'registered',
                include_patterns JSONB,
                exclude_patterns JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS index_generations (
                id UUID PRIMARY KEY,
                repository_id UUID NOT NULL REFERENCES repositories(id),
                state VARCHAR(32) NOT NULL DEFAULT 'building',
                embedding_model VARCHAR(255),
                embedding_version VARCHAR(255),
                embedding_dimension INTEGER,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS files (
                id UUID PRIMARY KEY,
                repository_id UUID NOT NULL REFERENCES repositories(id),
                relative_path VARCHAR(2048) NOT NULL,
                language VARCHAR(64),
                size_bytes INTEGER NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                git_head VARCHAR(40),
                worktree_dirty BOOLEAN NOT NULL DEFAULT FALSE,
                deleted BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_repo_files_path UNIQUE (repository_id, relative_path)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS chunks (
                id UUID PRIMARY KEY,
                file_id UUID NOT NULL REFERENCES files(id),
                generation_id UUID NOT NULL REFERENCES index_generations(id),
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                chunk_type VARCHAR(32) NOT NULL DEFAULT 'file',
                symbol_name VARCHAR(512),
                content_hash VARCHAR(64) NOT NULL,
                content TEXT NOT NULL,
                estimated_tokens INTEGER NOT NULL DEFAULT 0,
                embedding vector(768),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS symbols (
                id UUID PRIMARY KEY,
                file_id UUID NOT NULL REFERENCES files(id),
                name VARCHAR(512) NOT NULL,
                fully_qualified VARCHAR(1024),
                kind VARCHAR(32) NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                parser_source VARCHAR(64) NOT NULL DEFAULT 'text',
                generation_id UUID NOT NULL REFERENCES index_generations(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """\
            CREATE TABLE IF NOT EXISTS index_jobs (
                id UUID PRIMARY KEY,
                repository_id UUID NOT NULL REFERENCES repositories(id),
                job_type VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                error_summary TEXT,
                dedupe_key VARCHAR(256),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.execute("DROP TABLE IF EXISTS index_jobs")
    op.execute("DROP TABLE IF EXISTS symbols")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS files")
    op.execute("DROP TABLE IF EXISTS index_generations")
    op.execute("DROP TABLE IF EXISTS repositories")
