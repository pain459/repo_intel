"""Hardening: add chunker version, RetrievalEvent fields, Memory fields, chunk dedup.

Revision ID: 004_phase6
Revises: 003_phase3
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "004_phase6"
down_revision: Union[str, None] = "003_phase3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. IndexGeneration: add chunker_version column
    # ------------------------------------------------------------------
    op.add_column(
        "index_generations",
        sa.Column(
            "chunker_version",
            sa.String(64),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # 2. Chunk: deduplicate then add unique constraint
    #    on (generation_id, content_hash)
    # ------------------------------------------------------------------
    # First, delete duplicate rows keeping the earliest one per group
    op.execute(
        """
        DELETE FROM chunks
         WHERE ctid NOT IN (
             SELECT MIN(ctid)
             FROM chunks
             GROUP BY generation_id, content_hash
         )
        """
    )

    op.create_unique_constraint(
        "uq_gen_chunk_content",
        "chunks",
        ["generation_id", "content_hash"],
    )

    # ------------------------------------------------------------------
    # 3. RetrievalEvent: add request_id, generation_id,
    #    selected_chunk_ids, stale_count
    # ------------------------------------------------------------------
    op.add_column(
        "retrieval_events",
        sa.Column(
            "request_id",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "retrieval_events",
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "retrieval_events",
        sa.Column(
            "selected_chunk_ids",
            postgresql.JSONB,
            nullable=True,
        ),
    )
    op.add_column(
        "retrieval_events",
        sa.Column(
            "stale_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ------------------------------------------------------------------
    # 4. Memory: add author, expiry_time
    # ------------------------------------------------------------------
    op.add_column(
        "memories",
        sa.Column(
            "author",
            sa.String(128),
            nullable=True,
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "expiry_time",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Reverse order
    op.drop_column("memories", "expiry_time")
    op.drop_column("memories", "author")

    op.drop_column("retrieval_events", "stale_count")
    op.drop_column("retrieval_events", "selected_chunk_ids")
    op.drop_column("retrieval_events", "generation_id")
    op.drop_column("retrieval_events", "request_id")

    op.drop_constraint("uq_gen_chunk_content", "chunks", type_="unique")

    op.drop_column("index_generations", "chunker_version")
