"""add state_snapshot and last_completed_node to analyses

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2024-01-08 00:00:00.000000+00:00

T-033: State Persistence.

Adds two columns to the ``analyses`` table that support InvestmentState
persistence and pipeline resumption:

``state_snapshot`` (JSONB, nullable)
    The full InvestmentState dict serialised as JSONB.  Written after
    every LangGraph node completes.  NULL until the planner node runs.
    On failure, holds the last valid state so the pipeline can resume
    from the last completed node without re-running earlier agents.

``last_completed_node`` (VARCHAR 64, nullable)
    The name of the most recently completed LangGraph node.  Set to the
    same value as state["current_node"] at each checkpoint.  The graph
    runner reads this to know which node to resume from.

``error_message`` (TEXT, nullable)
    Already exists as a nullable column from the initial schema (T-016).
    No change needed.

Rollback safety: both new columns are nullable with no server_default,
so the downgrade simply drops them.  Existing rows are unaffected.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- state_snapshot: full InvestmentState JSON persisted after each node --
    op.add_column(
        "analyses",
        sa.Column(
            "state_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Full InvestmentState serialised as JSONB -- updated after "
                "each LangGraph node; NULL until first checkpoint is written"
            ),
        ),
    )

    # -- last_completed_node: which node wrote the most recent snapshot --------
    op.add_column(
        "analyses",
        sa.Column(
            "last_completed_node",
            sa.String(64),
            nullable=True,
            comment=(
                "LangGraph node name that last completed -- used to resume "
                "the pipeline from the correct checkpoint on failure"
            ),
        ),
    )

    # -- index on last_completed_node for dashboard queries --
    op.create_index(
        "ix_analyses_last_completed_node",
        "analyses",
        ["last_completed_node"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_last_completed_node", table_name="analyses")
    op.drop_column("analyses", "last_completed_node")
    op.drop_column("analyses", "state_snapshot")
