"""Stale chunk column for DB-level filtering during retrieval.

Revision ID: 005_phase7
Revises: 004_phase6
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_phase7"
down_revision: Union[str, None] = "004_phase6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add stale boolean to chunks, defaulting to False
    op.add_column(
        "chunks",
        sa.Column(
            "stale",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Mark chunks belonging to non-active generations as stale
    op.execute(
        """
        UPDATE chunks
           SET stale = TRUE
         WHERE NOT EXISTS (
             SELECT 1 FROM index_generations
              WHERE index_generations.id = chunks.generation_id
                AND index_generations.state = 'active'
         )
        """
    )


def downgrade() -> None:
    op.drop_column("chunks", "stale")
