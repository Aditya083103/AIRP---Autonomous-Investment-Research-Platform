# backend/migrations/versions/20240101_0000_a1b2c3d4e5f6_initial_schema.py
"""initial schema: users, companies, analyses, agent_outputs, investment_memos

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2024-01-01 00:00:00.000000+00:00

Creates the five core AIRP tables and their supporting Enum types.
All tables use UUID primary keys with server-side gen_random_uuid().
All timestamps are TIMESTAMPTZ stored in UTC.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PostgreSQL ENUM types ────────────────────────────────────────────────
    # Create enum types explicitly so downgrade() can drop them cleanly.
    # Alembic autogenerate would create these inline; we create them upfront
    # so every table that references the same enum shares one PG type object.

    analysis_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="analysis_status",
        create_type=False,
    )
    analysis_status.create(op.get_bind(), checkfirst=True)

    verdict = postgresql.ENUM(
        "BUY",
        "HOLD",
        "SELL",
        name="verdict",
        create_type=False,
    )
    verdict.create(op.get_bind(), checkfirst=True)

    agent_name = postgresql.ENUM(
        "fundamental_analyst",
        "technical_analyst",
        "news_sentiment",
        "macro_economist",
        "risk_officer",
        "contrarian_investor",
        "valuation_agent",
        "portfolio_manager",
        name="agent_name",
        create_type=False,
    )
    agent_name.create(op.get_bind(), checkfirst=True)

    exchange = postgresql.ENUM(
        "NSE",
        "BSE",
        name="exchange",
        create_type=False,
    )
    exchange.create(op.get_bind(), checkfirst=True)

    # ── Table: users ─────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "clerk_user_id",
            sa.String(128),
            nullable=False,
            comment="Opaque Clerk user ID received from JWT (e.g. user_2abc...)",
        ),
        sa.Column(
            "email",
            sa.String(320),
            nullable=False,
            comment="User's primary email address from Clerk",
        ),
        sa.Column(
            "display_name",
            sa.String(200),
            nullable=True,
            comment="Display name from Clerk profile (first + last name)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when the local user record was first created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp of the most recent profile update",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clerk_user_id"),
        comment="Local user registry — one row per Clerk-authenticated user",
    )
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── Table: companies ─────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(300),
            nullable=False,
            comment=("Full company name " "(e.g. 'Tata Consultancy Services Limited')"),
        ),
        sa.Column(
            "ticker",
            sa.String(30),
            nullable=False,
            comment="Exchange ticker without suffix (e.g. 'TCS', 'INFY')",
        ),
        sa.Column(
            "ticker_yf",
            sa.String(40),
            nullable=False,
            comment=("Yahoo Finance ticker with suffix " "(e.g. 'TCS.NS', 'INFY.NS')"),
        ),
        sa.Column(
            "exchange",
            postgresql.ENUM(
                "NSE",
                "BSE",
                name="exchange",
                create_type=False,
            ),
            nullable=False,
            comment="Primary listing exchange: NSE or BSE",
        ),
        sa.Column(
            "sector",
            sa.String(100),
            nullable=True,
            comment=("GICS sector classification " "(e.g. 'Information Technology')"),
        ),
        sa.Column(
            "industry",
            sa.String(150),
            nullable=True,
            comment=(
                "Industry sub-classification " "(e.g. 'IT Services & Consulting')"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker",
            "exchange",
            name="uq_companies_ticker_exchange",
        ),
        comment=(
            "Normalised company registry — " "one row per (ticker, exchange) pair"
        ),
    )
    op.create_index("ix_companies_ticker_yf", "companies", ["ticker_yf"])

    # ── Table: analyses ──────────────────────────────────────────────────────
    op.create_table(
        "analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment=(
                "Opaque job ID returned to the frontend " "on POST /analysis/start"
            ),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → companies.id",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id — the user who triggered this analysis",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                name="analysis_status",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
            comment=("Lifecycle state: pending → running → completed | failed"),
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment=("Human-readable error if status='failed'; NULL otherwise"),
        ),
        sa.Column(
            "debate_rounds_completed",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment=(
                "Number of agent debate rounds completed "
                "(max = settings.debate_rounds)"
            ),
        ),
        sa.Column(
            "duration_seconds",
            sa.Integer,
            nullable=True,
            comment=(
                "Wall-clock seconds from job start to completion; " "NULL while running"
            ),
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment=("UTC timestamp when the user submitted the analysis request"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=("UTC timestamp when the LangGraph pipeline began executing"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "UTC timestamp when the pipeline finished " "(success or failure)"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment=("Analysis job registry — " "one row per user-triggered analysis run"),
    )
    op.create_index("ix_analyses_company_id", "analyses", ["company_id"])
    op.create_index("ix_analyses_user_id", "analyses", ["user_id"])
    op.create_index("ix_analyses_status", "analyses", ["status"])
    op.create_index("ix_analyses_requested_at", "analyses", ["requested_at"])

    # ── Table: agent_outputs ─────────────────────────────────────────────────
    op.create_table(
        "agent_outputs",
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
            comment="FK → analyses.id",
        ),
        sa.Column(
            "agent_name",
            postgresql.ENUM(
                "fundamental_analyst",
                "technical_analyst",
                "news_sentiment",
                "macro_economist",
                "risk_officer",
                "contrarian_investor",
                "valuation_agent",
                "portfolio_manager",
                name="agent_name",
                create_type=False,
            ),
            nullable=False,
            comment=(
                "Which of the 8 investment committee agents " "produced this output"
            ),
        ),
        sa.Column(
            "output_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full Pydantic model output serialised as JSONB",
        ),
        sa.Column(
            "tokens_used",
            sa.Integer,
            nullable=True,
            comment=(
                "Total tokens consumed by this agent call " "(prompt + completion)"
            ),
        ),
        sa.Column(
            "latency_ms",
            sa.Integer,
            nullable=True,
            comment=("Wall-clock milliseconds for this agent's LLM call"),
        ),
        sa.Column(
            "langsmith_run_id",
            sa.String(64),
            nullable=True,
            comment=("LangSmith run UUID for correlation with the trace dashboard"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when this agent output was written",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "agent_name",
            name="uq_agent_outputs_analysis_agent",
        ),
        comment=("Per-agent structured outputs — " "one row per agent per analysis"),
    )
    op.create_index(
        "ix_agent_outputs_analysis_id",
        "agent_outputs",
        ["analysis_id"],
    )

    # ── Table: investment_memos ──────────────────────────────────────────────
    op.create_table(
        "investment_memos",
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
            unique=True,
            comment="FK → analyses.id — one memo per analysis (1:1)",
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
            comment="Final investment recommendation: BUY, HOLD, or SELL",
        ),
        sa.Column(
            "conviction_score",
            sa.Integer,
            nullable=False,
            comment="Portfolio Manager confidence 1 (low) – 10 (high)",
        ),
        sa.Column(
            "executive_summary",
            sa.Text,
            nullable=False,
            comment=("2–3 paragraph executive summary written by Portfolio Manager"),
        ),
        sa.Column(
            "investment_thesis",
            sa.Text,
            nullable=False,
            comment=("Core investment thesis supporting the BUY/HOLD/SELL decision"),
        ),
        sa.Column(
            "bull_case",
            sa.Text,
            nullable=False,
            comment=("Bull case argument synthesised from research agent outputs"),
        ),
        sa.Column(
            "bear_case",
            sa.Text,
            nullable=False,
            comment=("Bear case — Contrarian Investor and Risk Officer arguments"),
        ),
        sa.Column(
            "risk_summary",
            sa.Text,
            nullable=False,
            comment="Top risks identified by the Risk Officer agent",
        ),
        sa.Column(
            "valuation_summary",
            sa.Text,
            nullable=False,
            comment=("DCF and peer comparison summary from Valuation Agent"),
        ),
        sa.Column(
            "price_target",
            sa.String(50),
            nullable=True,
            comment=(
                "Implied price target from DCF (e.g. '₹4,200'); "
                "NULL when valuation is inconclusive"
            ),
        ),
        sa.Column(
            "pdf_path",
            sa.String(500),
            nullable=True,
            comment=(
                "Relative path to the generated PDF file "
                "(e.g. 'memos/TCS-2024-Q3.pdf'); NULL until PDF is generated"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when the memo was written",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment=("Final investment memos — one per completed analysis"),
    )
    op.create_index(
        "ix_investment_memos_verdict",
        "investment_memos",
        ["verdict"],
    )
    op.create_index(
        "ix_investment_memos_analysis_id",
        "investment_memos",
        ["analysis_id"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("investment_memos")
    op.drop_table("agent_outputs")
    op.drop_table("analyses")
    op.drop_table("companies")
    op.drop_table("users")

    # Drop PostgreSQL ENUM types
    op.execute("DROP TYPE IF EXISTS verdict")
    op.execute("DROP TYPE IF EXISTS agent_name")
    op.execute("DROP TYPE IF EXISTS analysis_status")
    op.execute("DROP TYPE IF EXISTS exchange")
