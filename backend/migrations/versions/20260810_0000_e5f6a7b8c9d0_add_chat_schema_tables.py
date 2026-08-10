# backend/migrations/versions/20260810_0000_e5f6a7b8c9d0_add_chat_schema_tables.py
"""add chat_sessions, chat_messages, user_preferences tables

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-10 00:00:00.000000+00:00

T-099: AIRP Assistant (Chatbot) — Phase 10. Creates the three tables the
chat feature is built on:

    chat_sessions     — one row per chat conversation. A session is either
                         *memo-scoped* (tied to a single analysis_id, used
                         for "ask about this memo" Q&A — see T-100) or
                         *portfolio-wide* (analysis_id is NULL, used for
                         cross-portfolio tool-calling questions — see
                         T-101, e.g. "which of my BUY calls are up this
                         month?").
    chat_messages      — one row per message in a session (user, assistant,
                          system, or tool-result), in the order the
                          conversation happened. ``tool_calls`` stores any
                          LangChain tool invocations an assistant message
                          made, as JSONB, so the transcript is fully
                          replayable without re-deriving it from logs.
    user_preferences   — one row per user, holding chat/display settings
                          (response verbosity, theme, notification and
                          watchlist preferences) read by the assistant and
                          the frontend settings panel.

This migration adds no new PostgreSQL ENUM type for exchanges — it reuses
the existing ``exchange`` type (created in the initial schema, T-016) for
``user_preferences.default_exchange`` via ``create_type=False``, the same
pattern the ``verdict_outcomes`` migration (T-087) used for ``verdict``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PostgreSQL ENUM types ────────────────────────────────────────────────
    # Created explicitly (not via inline Column(Enum(...))) so downgrade()
    # can drop them cleanly and every table that references the same enum
    # shares one PG type object — matches the pattern in the initial schema
    # migration (T-016).

    chat_session_type = postgresql.ENUM(
        "memo_scoped",
        "portfolio_wide",
        name="chat_session_type",
        create_type=False,
    )
    chat_session_type.create(op.get_bind(), checkfirst=True)

    chat_message_role = postgresql.ENUM(
        "user",
        "assistant",
        "system",
        "tool",
        name="chat_message_role",
        create_type=False,
    )
    chat_message_role.create(op.get_bind(), checkfirst=True)

    theme_preference = postgresql.ENUM(
        "light",
        "dark",
        "system",
        name="theme_preference",
        create_type=False,
    )
    theme_preference.create(op.get_bind(), checkfirst=True)

    chat_response_style = postgresql.ENUM(
        "concise",
        "detailed",
        name="chat_response_style",
        create_type=False,
    )
    chat_response_style.create(op.get_bind(), checkfirst=True)

    # exchange already exists (created in the initial schema, T-016) —
    # reused as-is via create_type=False, no new type created here.
    exchange = postgresql.ENUM(
        "NSE",
        "BSE",
        name="exchange",
        create_type=False,
    )

    # ── Table: chat_sessions ────────────────────────────────────────────────
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id — the user this conversation belongs to",
        ),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                "FK → analyses.id for a memo-scoped session (T-100); "
                "NULL for a portfolio-wide session (T-101)"
            ),
        ),
        sa.Column(
            "session_type",
            chat_session_type,
            nullable=False,
            comment="'memo_scoped' (single analysis) or 'portfolio_wide'",
        ),
        sa.Column(
            "title",
            sa.String(200),
            nullable=True,
            comment="Optional display title, e.g. auto-derived from the first message",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when the session was started",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp of the most recent message in this session",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(session_type = 'memo_scoped' AND analysis_id IS NOT NULL) OR "
            "(session_type = 'portfolio_wide' AND analysis_id IS NULL)",
            name="ck_chat_sessions_scope_consistency",
        ),
        comment=(
            "AIRP Assistant chat sessions — one row per conversation, "
            "either scoped to a single analysis or portfolio-wide"
        ),
    )
    op.create_index(
        "ix_chat_sessions_user_id",
        "chat_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_chat_sessions_analysis_id",
        "chat_sessions",
        ["analysis_id"],
    )

    # ── Table: chat_messages ────────────────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → chat_sessions.id",
        ),
        sa.Column(
            "role",
            chat_message_role,
            nullable=False,
            comment="'user' | 'assistant' | 'system' | 'tool'",
        ),
        sa.Column(
            "content",
            sa.Text,
            nullable=False,
            comment="Message text (assistant messages may also carry tool_calls)",
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB,
            nullable=True,
            comment=(
                "LangChain tool invocations made by this assistant message "
                "(name, args, result), if any; NULL for plain text messages"
            ),
        ),
        sa.Column(
            "tool_name",
            sa.String(100),
            nullable=True,
            comment="Which tool produced this message, when role='tool'",
        ),
        sa.Column(
            "tokens_used",
            sa.Integer,
            nullable=True,
            comment="Total tokens consumed generating this message, if known",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp when this message was recorded",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment=(
            "AIRP Assistant chat messages — one row per message, "
            "ordered by created_at within a session"
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id",
        "chat_messages",
        ["session_id"],
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )

    # ── Table: user_preferences ─────────────────────────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id — one preferences row per user",
        ),
        sa.Column(
            "theme",
            theme_preference,
            nullable=False,
            server_default="system",
            comment="UI theme: 'light' | 'dark' | 'system'",
        ),
        sa.Column(
            "chat_response_style",
            chat_response_style,
            nullable=False,
            server_default="concise",
            comment="AIRP Assistant reply verbosity: 'concise' | 'detailed'",
        ),
        sa.Column(
            "default_exchange",
            exchange,
            nullable=True,
            comment="Preferred exchange (NSE/BSE) to default new analyses to",
        ),
        sa.Column(
            "watchlist_tickers",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment=(
                "JSON array of ticker strings the user tracks " "(e.g. ['TCS', 'INFY'])"
            ),
        ),
        sa.Column(
            "email_notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Whether to email the user on completed analyses / accuracy runs",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="UTC timestamp of the most recent preference change",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            name="uq_user_preferences_user_id",
        ),
        comment="Per-user chat and display preferences — one row per user",
    )
    op.create_index(
        "ix_user_preferences_user_id",
        "user_preferences",
        ["user_id"],
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")

    op.drop_index("ix_chat_messages_session_id_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_analysis_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    # Drop PostgreSQL ENUM types created by this migration.
    # 'exchange' is NOT dropped here — it is owned by the initial schema
    # migration (T-016) and is still in use by companies.exchange.
    op.execute("DROP TYPE IF EXISTS chat_response_style")
    op.execute("DROP TYPE IF EXISTS theme_preference")
    op.execute("DROP TYPE IF EXISTS chat_message_role")
    op.execute("DROP TYPE IF EXISTS chat_session_type")
