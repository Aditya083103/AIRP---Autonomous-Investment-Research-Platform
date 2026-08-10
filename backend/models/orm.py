# backend/models/orm.py
"""
AIRP — SQLAlchemy ORM Models (T-016, T-087)

Defines the six core tables that back the AIRP system:

    users            — Self-hosted auth (T-046); local row per registered user
    companies        — Normalised company/ticker registry (avoid re-resolving)
    analyses         — One row per analysis job; tracks status & timing
    agent_outputs    — One row per agent per analysis; stores raw JSON output
    investment_memos — Final PDF memo and BUY/HOLD/SELL verdict per analysis
    verdict_outcomes — Verdict Accuracy Tracker (T-087); scores a past verdict
                       against the real price outcome at a later horizon
    chat_sessions     — AIRP Assistant (T-099); one row per chat conversation,
                        memo-scoped (analysis_id set) or portfolio-wide (NULL)
    chat_messages     — AIRP Assistant (T-099); one row per message in a session
    user_preferences  — AIRP Assistant (T-099); one row per user's chat/display
                        settings

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
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text as sa_text,
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

#: Whether a chat session is scoped to one analysis or spans the portfolio
ChatSessionTypeEnum = Enum(
    "memo_scoped",
    "portfolio_wide",
    name="chat_session_type",
)

#: Speaker role for a single chat message
ChatMessageRoleEnum = Enum(
    "user",
    "assistant",
    "system",
    "tool",
    name="chat_message_role",
)

#: UI theme preference
ThemePreferenceEnum = Enum(
    "light",
    "dark",
    "system",
    name="theme_preference",
)

#: AIRP Assistant reply verbosity preference
ChatResponseStyleEnum = Enum(
    "concise",
    "detailed",
    name="chat_response_style",
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
    Local user record for self-hosted email/password authentication (T-046).

    Originally designed around Clerk as the auth provider (clerk_user_id
    as the canonical identity key); migrated to self-hosted auth in T-046
    per the actual task requirements (POST /auth/register, POST
    /auth/login with bcrypt-hashed passwords, self-issued JWTs). ``email``
    is now the canonical, unique identity key; ``password_hash`` stores a
    bcrypt hash (via passlib) and is never serialised in any API response.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True,
        comment="User's email address — canonical login identity",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash of the user's password (passlib CryptContext)",
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Optional display name shown in the dashboard",
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="true",
        comment="False disables login without deleting the account/history",
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
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    preferences: Mapped[Optional[UserPreferences]] = relationship(
        "UserPreferences",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = ({"comment": "Local user registry — one row per registered user"},)

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
    verdict_outcomes: Mapped[list[VerdictOutcome]] = relationship(
        "VerdictOutcome",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        "ChatSession",
        back_populates="analysis",
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


# ---------------------------------------------------------------------------
# Table: verdict_outcomes
# ---------------------------------------------------------------------------


class VerdictOutcome(Base):
    """
    Verdict Accuracy Tracker row (T-087, Phase 8).

    One row per (analysis, evaluation horizon) pair. Records the verdict
    that was made — and the price at the moment it was made — so that a
    later background job can look up the real market price at
    ``verdict_date + evaluation_horizon_days`` and compute whether the
    Portfolio Manager's BUY/HOLD/SELL call was directionally correct.

    Rows are written twice in their lifecycle:

    1. **At verdict time** — ``analysis_id``, ``ticker``, ``verdict``,
       ``conviction_score``, ``price_at_verdict``, ``verdict_date``, and
       ``evaluation_horizon_days`` are populated; the four "outcome"
       columns (``price_at_evaluation``, ``price_change_pct``,
       ``directional_correct``, ``evaluated_at``) are ``NULL``.
    2. **At evaluation time** — once ``evaluation_horizon_days`` has
       elapsed, a scheduled job fetches the current price, computes
       ``price_change_pct``, derives ``directional_correct`` (does the
       sign of the price move agree with a BUY/SELL verdict; HOLD is
       scored separately by the evaluation service), and stamps
       ``evaluated_at``.

    A single analysis can be evaluated at more than one horizon (e.g. 30
    days and 90 days out) to track short- vs. medium-term accuracy
    separately, so the natural key is ``(analysis_id,
    evaluation_horizon_days)`` rather than ``analysis_id`` alone.
    """

    __tablename__ = "verdict_outcomes"

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
        comment="FK → analyses.id — the analysis this outcome tracks",
    )
    ticker: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="Yahoo Finance ticker at verdict time (e.g. 'TCS.NS')",
    )
    verdict: Mapped[str] = mapped_column(
        VerdictEnum,
        nullable=False,
        comment="The BUY/HOLD/SELL verdict being tracked for accuracy",
    )
    conviction_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Portfolio Manager confidence 1 (low) – 10 (high) at verdict time",
    )
    price_at_verdict: Mapped[float] = mapped_column(
        Numeric(12, 4, asdecimal=False),
        nullable=False,
        comment="Closing price of the ticker on verdict_date",
    )
    verdict_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC timestamp the verdict was issued (Analysis.completed_at)",
    )
    evaluation_horizon_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Days after verdict_date at which accuracy is evaluated (e.g. 30, 90)",
    )
    price_at_evaluation: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 4, asdecimal=False),
        nullable=True,
        comment="Closing price at verdict_date + horizon; NULL until evaluated",
    )
    price_change_pct: Mapped[Optional[float]] = mapped_column(
        Numeric(8, 4, asdecimal=False),
        nullable=True,
        comment=(
            "Percent change from price_at_verdict to price_at_evaluation; "
            "NULL until evaluated"
        ),
    )
    directional_correct: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment=(
            "Whether the verdict's implied direction matched the actual "
            "price move; NULL until evaluated"
        ),
    )
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the outcome evaluation job ran; NULL until run",
    )

    # Relationships
    analysis: Mapped[Analysis] = relationship(
        "Analysis",
        back_populates="verdict_outcomes",
    )

    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "evaluation_horizon_days",
            name="uq_verdict_outcomes_analysis_horizon",
        ),
        Index("ix_verdict_outcomes_ticker", "ticker"),
        Index("ix_verdict_outcomes_verdict_date", "verdict_date"),
        {
            "comment": (
                "Verdict Accuracy Tracker — scores past verdicts against "
                "real price outcomes at one or more evaluation horizons"
            )
        },
    )

    def __repr__(self) -> str:
        return (
            f"<VerdictOutcome analysis={self.analysis_id}"
            f" ticker={self.ticker!r}"
            f" verdict={self.verdict!r}"
            f" horizon={self.evaluation_horizon_days}d>"
        )


# ---------------------------------------------------------------------------
# Table: chat_sessions
# ---------------------------------------------------------------------------


class ChatSession(Base):
    """
    AIRP Assistant chat session (T-099, Phase 10).

    One row per conversation. A session is either:

    * **memo-scoped** — ``session_type='memo_scoped'``, ``analysis_id`` set —
      used for "ask about this memo" Q&A grounded in one analysis's agent
      outputs, debate transcript, and decision (T-100 builds the context
      builder this scope feeds).
    * **portfolio-wide** — ``session_type='portfolio_wide'``,
      ``analysis_id`` NULL — used for cross-portfolio questions answered via
      LangChain tool calls over the user's full analysis history and
      uploaded documents (T-101).

    A CHECK constraint (``ck_chat_sessions_scope_consistency``) enforces
    that these two are never mismatched: a memo-scoped row always carries
    its analysis, and a portfolio-wide row never does.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → users.id — the user this conversation belongs to",
    )
    analysis_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment=(
            "FK → analyses.id for a memo-scoped session (T-100); "
            "NULL for a portfolio-wide session (T-101)"
        ),
    )
    session_type: Mapped[str] = mapped_column(
        ChatSessionTypeEnum,
        nullable=False,
        comment="'memo_scoped' (single analysis) or 'portfolio_wide'",
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Optional display title, e.g. auto-derived from the first message",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the session was started",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp of the most recent message in this session",
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        back_populates="chat_sessions",
    )
    analysis: Mapped[Optional[Analysis]] = relationship(
        "Analysis",
        back_populates="chat_sessions",
    )
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_id", "user_id"),
        Index("ix_chat_sessions_analysis_id", "analysis_id"),
        CheckConstraint(
            "(session_type = 'memo_scoped' AND analysis_id IS NOT NULL) OR "
            "(session_type = 'portfolio_wide' AND analysis_id IS NULL)",
            name="ck_chat_sessions_scope_consistency",
        ),
        {
            "comment": (
                "AIRP Assistant chat sessions — one row per conversation, "
                "either scoped to a single analysis or portfolio-wide"
            )
        },
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} type={self.session_type!r}>"


# ---------------------------------------------------------------------------
# Table: chat_messages
# ---------------------------------------------------------------------------


class ChatMessage(Base):
    """
    A single message within a chat session (T-099, Phase 10).

    Ordered within a session by ``created_at`` — the ``ChatSession.messages``
    relationship reads back in that order so the transcript replays
    correctly. ``tool_calls`` preserves any LangChain tool invocations an
    assistant message made (name, args, result) as JSONB, matching the
    ``agent_outputs.output_json`` pattern (T-016) of storing structured
    Pydantic/tool output directly rather than re-deriving it from logs.
    """

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → chat_sessions.id",
    )
    role: Mapped[str] = mapped_column(
        ChatMessageRoleEnum,
        nullable=False,
        comment="'user' | 'assistant' | 'system' | 'tool'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message text (assistant messages may also carry tool_calls)",
    )
    tool_calls: Mapped[Optional[dict]] = mapped_column(  # type: ignore[type-arg]
        JSONB,
        nullable=True,
        comment=(
            "LangChain tool invocations made by this assistant message "
            "(name, args, result), if any; NULL for plain text messages"
        ),
    )
    tool_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Which tool produced this message, when role='tool'",
    )
    tokens_used: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Total tokens consumed generating this message, if known",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when this message was recorded",
    )

    # Relationships
    session: Mapped[ChatSession] = relationship(
        "ChatSession",
        back_populates="messages",
    )

    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id"),
        Index(
            "ix_chat_messages_session_id_created_at",
            "session_id",
            "created_at",
        ),
        {
            "comment": (
                "AIRP Assistant chat messages — one row per message, "
                "ordered by created_at within a session"
            )
        },
    )

    def __repr__(self) -> str:
        return f"<ChatMessage session={self.session_id} role={self.role!r}>"


# ---------------------------------------------------------------------------
# Table: user_preferences
# ---------------------------------------------------------------------------


class UserPreferences(Base):
    """
    Per-user chat and display preferences (T-099, Phase 10).

    One row per user (enforced by the unique FK on ``user_id``), created
    lazily on first access rather than at registration time — a user with
    no row yet simply gets the column defaults applied by the service
    layer. Read by the AIRP Assistant (response verbosity) and the
    frontend settings panel (theme, default exchange, watchlist,
    notifications).
    """

    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="FK → users.id — one preferences row per user",
    )
    theme: Mapped[str] = mapped_column(
        ThemePreferenceEnum,
        nullable=False,
        default="system",
        server_default="system",
        comment="UI theme: 'light' | 'dark' | 'system'",
    )
    chat_response_style: Mapped[str] = mapped_column(
        ChatResponseStyleEnum,
        nullable=False,
        default="concise",
        server_default="concise",
        comment="AIRP Assistant reply verbosity: 'concise' | 'detailed'",
    )
    default_exchange: Mapped[Optional[str]] = mapped_column(
        ExchangeEnum,
        nullable=True,
        comment="Preferred exchange (NSE/BSE) to default new analyses to",
    )
    watchlist_tickers: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB,
        nullable=False,
        default=list,
        server_default=sa_text("'[]'::jsonb"),
        comment="JSON array of ticker strings the user tracks (e.g. ['TCS', 'INFY'])",
    )
    email_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether to email the user on completed analyses / accuracy runs",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp of the most recent preference change",
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        back_populates="preferences",
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
        Index("ix_user_preferences_user_id", "user_id"),
        {"comment": "Per-user chat and display preferences — one row per user"},
    )

    def __repr__(self) -> str:
        return f"<UserPreferences user={self.user_id} theme={self.theme!r}>"
