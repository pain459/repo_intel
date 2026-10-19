"""Symbol edges table for dependency graph traversal.

Revision ID: 006_phase10
Revises: 005_phase7
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_phase10"
down_revision: Union[str, None] = "005_phase7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "symbol_edges",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.UUID(as_uuid=True), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("from_symbol_id", sa.UUID(as_uuid=True), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("to_symbol_id", sa.UUID(as_uuid=True), sa.ForeignKey("symbols.id"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("evidence_location", sa.String(512), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("0.5")),
        sa.Column("generation_id", sa.UUID(as_uuid=True), sa.ForeignKey("index_generations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("from_symbol_id", "to_symbol_id", "relation_type", name="uq_symbol_edge"),
    )
    # Index for fast graph traversal
    op.create_index("ix_symbol_edges_from", "symbol_edges", ["from_symbol_id"])
    op.create_index("ix_symbol_edges_to", "symbol_edges", ["to_symbol_id"])


def downgrade() -> None:
    op.drop_index("ix_symbol_edges_from")
    op.drop_index("ix_symbol_edges_to")
    op.drop_table("symbol_edges")
