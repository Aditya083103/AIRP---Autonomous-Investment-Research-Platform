# backend/models/orm.py
"""
AIRP — SQLAlchemy ORM Models (T-016)

Defines the five core tables that back the AIRP system:

    users            — Clerk-managed auth; local row per registered user
    companies        — Normalised company/ticker registry (avoid re-resolving)
    analyses         — One row per analysis job; tracks status & timing
    agent_outputs    — One row per agent per analysis; stores raw JSON output
    investment_memos — Final PDF memo and BUY/HOLD/SELL verdict per analysis

Design decisions
────────────────
* All PKs are UUIDs (server-default ``gen_random_uuid()``) so IDs are safe
  to expose in REST responses and can be generated client-side if needed.
* Timestamps use ``TIMESTAMP WITH TIME ZONE`` (PostgreSQL ``TIMESTAMPTZ``)
  stored in UTC.  SQLAlchemy maps this to ``DateTime(timezone=True)``.
* ``agent_outputs.output_json`` is stored as ``JSONB`` — PostgreSQL's binary
  JSON type — which supports GIN-index queries and is ~20 % faster to read
  than plain JSON.
* Relationships are declared with ``relationship()`` for ORM convenience but
  all foreign key constraints are enforced at the database level via
  ``ForeignKey`` with ``ondelete`` rules.
* Alembic autogenerate reads this module via ``env.py`` target_metadata.

Usage (inside FastAPI routes / services):
    from backend.models.orm import Analysis, AgentOutput
    from backend.db.session import get_async_session

    async with get_async_session() as session:
        analysis = Analysis(company_id=..., requested_by=...)
        session.add(analysis)
        await session.commit()
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

# ---------------------------------------------------------------------------
# Enumerations — stored as PostgreSQL ENUM types for data integrity
# ---------------------------------------------------------------------------

#: Lifecycle states for an analysis job
AnalysisStatus = Enum(
    "pending",
    "running",
    "completed",
    "failed",
    name="analysis_status",
)

#: Final verdict produced by the Portfolio Manager agent
VerdictEnum = Enum(
    "BUY",
    "HOLD",
    "SELL",
    name="verdict",
)

#: The eight AIRP investment committee agents
AgentNameEnum = Enum(
    "fundamental_analyst",
    "technical_analyst",
    "news_sentiment",
    "macro_economist",
    "risk_officer",
    "contrarian_investor",
    "valuation_agent",
    "portfolio_manager",
    name="agent_name",
)

#: Indian stock exchanges supported by AIRP
ExchangeEnum = Enum(
    "NSE",
    "BSE",
    name="exchange",
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """
    Shared declarative base for all AIRP ORM models.

    All models inherit from this class so Alembic's ``target_metadata``
    can discover every table in a single import.
    """


# ---------------------------------------------------------------------------
# Table: users
# ---------------------------------------------------------------------------


class User(Base):
    """
    Local user record mirroring Clerk's auth identity.

    Clerk manages authentication; AIRP stores only the fields needed to
    associate analyses with a user and display basic profile information.
    The ``clerk_user_id`` is the canonical identifier received from Clerk
    JWTs and is the join key for all auth checks.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    clerk_user_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
        comment="Opaque Clerk user ID received from JWT (e.g. user_2abc...)",
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        comment="User's primary email address from Clerk",
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Display name from Clerk profile (first + last name)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the local user record was first created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp of the most recent profile update",
    )

    # Relationships
    analyses: Mapped[list[Analysis]] = relationship(
        "Analysis",
        back_populates="requested_by_user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        {"comment": "Local user registry — one row per Clerk-authenticated user"},
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


# ---------------------------------------------------------------------------
# Table: companies
# ---------------------------------------------------------------------------


class Company(Base):
    """
    Normalised company registry.

    Stores the resolved ticker, exchange, and display name for every company
    that has been analysed.  This avoids re-resolving ``'TCS' → 'TCS.NS'``
    on every analysis run and provides a single place to correct bad mappings.

    The ``(ticker, exchange)`` pair is unique — the same company can exist on
    both NSE and BSE but with different tickers.
    """

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        comment="Full company name (e.g. 'Tata Consultancy Services Limited')",
    )
    ticker: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Exchange ticker without suffix (e.g. 'TCS', 'INFY')",
    )
    ticker_yf: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="Yahoo Finance ticker with suffix (e.g. 'TCS.NS', 'INFY.NS')",
    )
    exchange: Mapped[str] = mapped_column(
        ExchangeEnum,
        nullable=False,
        comment="Primary listing exchange: NSE or BSE",
    )
    sector: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="GICS sector classification (e.g. 'Information Technology')",
    )
    industry: Mapped[Optional[str]] = mapped_column(
        String(150),
        nullable=True,
        comment="Industry sub-classification (e.g. 'IT Services & Consulting')",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    analyses: Mapped[list[Analysis]] = relationship(
        "Analysis",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("ticker", "exchange", name="uq_companies_ticker_exchange"),
        Index("ix_companies_ticker_yf", "ticker_yf"),
        {
            "comment": (
                "Normalised company registry — one row per (ticker, exchange) pair"
            )
        },
    )

    def __repr__(self) -> str:
        return f"<Company {self.ticker}:{self.exchange}>"


# ---------------------------------------------------------------------------
# Table: analyses
# ---------------------------------------------------------------------------


class Analysis(Base):
    """
    One row per analysis job triggered by a user.

    Tracks the full lifecycle from ``pending`` through ``running`` to
    ``completed`` or ``failed``.  The LangGraph pipeline writes its
    final state back here when the Portfolio Manager completes.

    ``duration_seconds`` is set on completion so the dashboard can display
    how long the analysis took without recalculating from timestamps.
    """

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="Opaque job ID returned to the frontend on POST /analysis/start",
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="FK → companies.id",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → users.id — the user who triggered this analysis",
    )
    status: Mapped[str] = mapped_column(
        AnalysisStatus,
        nullable=False,
        default="pending",
        server_default="pending",
        comment="Lifecycle state: pending → running → completed | failed",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable error if status='failed'; NULL otherwise",
    )
    debate_rounds_completed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment=(
            "Number of agent debate rounds completed " "(max = settings.debate_rounds)"
        ),
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Wall-clock seconds from job start to completion; NULL while running",
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the user submitted the analysis request",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the LangGraph pipeline began executing",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the pipeline finished (success or failure)",
    )

    # Relationships
    company: Mapped[Company] = relationship(
        "Company",
        back_populates="analyses",
    )
    requested_by_user: Mapped[User] = relationship(
        "User",
        back_populates="analyses",
    )
    agent_outputs: Mapped[list[AgentOutput]] = relationship(
        "AgentOutput",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )
    investment_memo: Mapped[Optional[InvestmentMemo]] = relationship(
        "InvestmentMemo",
        back_populates="analysis",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_analyses_status", "status"),
        Index("ix_analyses_requested_at", "requested_at"),
        {
            "comment": (
                "Analysis job registry — one row per user-triggered analysis run"
            )
        },
    )

    def __repr__(self) -> str:
        return f"<Analysis id={self.id} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Table: agent_outputs
# ---------------------------------------------------------------------------


class AgentOutput(Base):
    """
    Raw structured output from a single agent in a single analysis.

    Every agent in the investment committee writes its Pydantic model output
    as JSONB here.  This gives full auditability — every claim an agent made
    is preserved alongside its token usage and latency, allowing post-hoc
    review and LangSmith correlation via ``langsmith_run_id``.

    One analysis produces up to 8 rows (one per agent).  The ``(analysis_id,
    agent_name)`` pair is unique so upserts are safe.
    """

    __tablename__ = "agent_outputs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → analyses.id",
    )
    agent_name: Mapped[str] = mapped_column(
        AgentNameEnum,
        nullable=False,
        comment="Which of the 8 investment committee agents produced this output",
    )
    output_json: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB,
        nullable=False,
        comment="Full Pydantic model output serialised as JSONB",
    )
    tokens_used: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Total tokens consumed by this agent call (prompt + completion)",
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Wall-clock milliseconds for this agent's LLM call",
    )
    langsmith_run_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="LangSmith run UUID for correlation with the trace dashboard",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when this agent output was written",
    )

    # Relationships
    analysis: Mapped[Analysis] = relationship(
        "Analysis",
        back_populates="agent_outputs",
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "agent_name",
            name="uq_agent_outputs_analysis_agent",
        ),
        Index(
            "ix_agent_outputs_analysis_id",
            "analysis_id",
        ),
        {"comment": ("Per-agent structured outputs — one row per agent per analysis")},
    )

    def __repr__(self) -> str:
        return (
            f"<AgentOutput analysis={self.analysis_id}" f" agent={self.agent_name!r}>"
        )


# ---------------------------------------------------------------------------
# Table: investment_memos
# ---------------------------------------------------------------------------


class InvestmentMemo(Base):
    """
    Final investment memo produced by the Portfolio Manager agent.

    One memo per analysis (enforced by the unique FK).  Stores both the
    structured content fields (executive summary, thesis, cases, risk,
    valuation) and the generated PDF as a file path reference.

    ``conviction_score`` is an integer 1–10 representing the Portfolio
    Manager's confidence level.  1 = very low conviction, 10 = very high.
    """

    __tablename__ = "investment_memos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="FK → analyses.id — one memo per analysis (1:1)",
    )
    verdict: Mapped[str] = mapped_column(
        VerdictEnum,
        nullable=False,
        comment="Final investment recommendation: BUY, HOLD, or SELL",
    )
    conviction_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Portfolio Manager confidence 1 (low) – 10 (high)",
    )
    executive_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="2–3 paragraph executive summary written by Portfolio Manager",
    )
    investment_thesis: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Core investment thesis supporting the BUY/HOLD/SELL decision",
    )
    bull_case: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Bull case argument synthesised from research agent outputs",
    )
    bear_case: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Bear case — Contrarian Investor and Risk Officer arguments",
    )
    risk_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Top risks identified by the Risk Officer agent",
    )
    valuation_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="DCF and peer comparison summary from Valuation Agent",
    )
    price_target: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment=(
            "Implied price target from DCF (e.g. '₹4,200'); "
            "NULL when valuation is inconclusive"
        ),
    )
    pdf_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment=(
            "Relative path to the generated PDF file "
            "(e.g. 'memos/TCS-2024-Q3.pdf'); NULL until PDF is generated"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the memo was written",
    )

    # Relationships
    analysis: Mapped[Analysis] = relationship(
        "Analysis",
        back_populates="investment_memo",
    )

    __table_args__ = (
        Index("ix_investment_memos_verdict", "verdict"),
        Index("ix_investment_memos_analysis_id", "analysis_id"),
        {"comment": ("Final investment memos — one per completed analysis")},
    )

    def __repr__(self) -> str:
        return (
            f"<InvestmentMemo analysis={self.analysis_id}"
            f" verdict={self.verdict!r}"
            f" score={self.conviction_score}>"
        )
