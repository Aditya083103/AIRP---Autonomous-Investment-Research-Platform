# backend/migrations/versions/20260801_0000_d4e5f6a7b8c9_add_verdict_outcomes_table.py
"""add verdict_outcomes table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-01 00:00:00.000000+00:00

T-087: Verdict Accuracy Tracker (Phase 8) — creates ``verdict_outcomes``,
one row per (analysis, evaluation horizon) pair, recording the verdict and
price at the moment it was issued so a later background job can score it
against the real market price at ``verdict_date + evaluation_horizon_days``.

This migration adds no new PostgreSQL ENUM type: ``verdict`` already
exists (created in the initial schema, T-016) and is reused as-is via
``create_type=False`` — the column references the existing type rather
than creating a duplicate.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Table: verdict_outcomes ──────────────────────────────────────────────
    op.create_table(
        "verdict_outcomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → analyses.id — the analysis this outcome tracks",
        ),
        sa.Column(
            "ticker",
            sa.String(40),
            nullable=False,
            comment="Yahoo Finance ticker at verdict time (e.g. 'TCS.NS')",
        ),
        sa.Column(
            "verdict",
            postgresql.ENUM(
                "BUY",
                "HOLD",
                "SELL",
                name="verdict",
                create_type=False,
            ),
            nullable=False,
            comment="The BUY/HOLD/SELL verdict being tracked for accuracy",
        ),
        sa.Column(
            "conviction_score",
            sa.Integer,
            nullable=False,
            comment=(
                "Portfolio Manager confidence 1 (low) – 10 (high) " "at verdict time"
            ),
        ),
        sa.Column(
            "price_at_verdict",
            sa.Numeric(12, 4),
            nullable=False,
            comment="Closing price of the ticker on verdict_date",
        ),
        sa.Column(
            "verdict_date",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="UTC timestamp the verdict was issued (Analysis.completed_at)",
        ),
        sa.Column(
            "evaluation_horizon_days",
            sa.Integer,
            nullable=False,
            comment=(
                "Days after verdict_date at which accuracy is evaluated "
                "(e.g. 30, 90)"
            ),
        ),
        sa.Column(
            "price_at_evaluation",
            sa.Numeric(12, 4),
            nullable=True,
            comment="Closing price at verdict_date + horizon; NULL until evaluated",
        ),
        sa.Column(
            "price_change_pct",
            sa.Numeric(8, 4),
            nullable=True,
            comment=(
                "Percent change from price_at_verdict to price_at_evaluation; "
                "NULL until evaluated"
            ),
        ),
        sa.Column(
            "directional_correct",
            sa.Boolean(),
            nullable=True,
            comment=(
                "Whether the verdict's implied direction matched the actual "
                "price move; NULL until evaluated"
            ),
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the outcome evaluation job ran; NULL until run",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "evaluation_horizon_days",
            name="uq_verdict_outcomes_analysis_horizon",
        ),
        comment=(
            "Verdict Accuracy Tracker — scores past verdicts against real "
            "price outcomes at one or more evaluation horizons"
        ),
    )
    op.create_index(
        "ix_verdict_outcomes_analysis_id",
        "verdict_outcomes",
        ["analysis_id"],
    )
    op.create_index(
        "ix_verdict_outcomes_ticker",
        "verdict_outcomes",
        ["ticker"],
    )
    op.create_index(
        "ix_verdict_outcomes_verdict_date",
        "verdict_outcomes",
        ["verdict_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_verdict_outcomes_verdict_date", table_name="verdict_outcomes")
    op.drop_index("ix_verdict_outcomes_ticker", table_name="verdict_outcomes")
    op.drop_index("ix_verdict_outcomes_analysis_id", table_name="verdict_outcomes")
    op.drop_table("verdict_outcomes")
