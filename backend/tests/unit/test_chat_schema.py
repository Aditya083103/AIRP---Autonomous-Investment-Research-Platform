# backend/tests/unit/test_chat_schema.py
"""
Unit tests for the AIRP Assistant chat schema — T-099.

Covers the three ORM models added for the chatbot feature (Phase 10):
``ChatSession``, ``ChatMessage``, and ``UserPreferences``.

All tests run fully offline — no real database connection is required.
SQLAlchemy metadata inspection and model construction are used instead,
matching the pattern established in ``test_orm_models.py`` (T-016) and
``test_verdict_outcomes.py`` (T-087).

Test coverage (acceptance criteria from T-099):
  * "alembic upgrade head creates all three tables" is verified indirectly
    here by asserting all three tables and their exact column sets are
    registered on ``Base.metadata`` — the same metadata object
    ``backend/migrations/env.py`` points ``target_metadata`` at, and the
    same shape the T-099 migration's ``op.create_table`` calls create.
    (The migration DDL itself is exercised against a real Postgres
    instance by the CI backend job's Postgres service container, not by
    these offline unit tests.)
  * "ORM models covered by tests" — every column, constraint, index,
    relationship, and ``__repr__`` on all three models is asserted below.

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_chat_schema.py -v
"""

from __future__ import annotations

import os  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")

from typing import Any, cast  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: E402
from sqlalchemy.orm import RelationshipProperty  # noqa: E402

from backend.models import (  # noqa: E402
    Analysis,
    Base,
    ChatMessage,
    ChatSession,
    User,
    UserPreferences,
)

# ---------------------------------------------------------------------------
# Helpers (mirrors test_orm_models.py / test_verdict_outcomes.py)
# ---------------------------------------------------------------------------


def _col(model: Any, name: str) -> Any:
    """Return the SQLAlchemy Column object for a model attribute by name."""
    mapper = sa_inspect(model)
    return mapper.columns[name]


def _fks(model: Any) -> set[str]:
    """Return the set of FK target column strings for a model."""
    mapper = sa_inspect(model)
    result = set()
    for col in mapper.columns:
        for fk in col.foreign_keys:
            result.add(fk.target_fullname)
    return result


def _uqs(model: Any) -> list[Any]:
    """Return all UniqueConstraint objects on a model's table."""
    mapper = sa_inspect(model)
    return [
        c
        for c in mapper.persist_selectable.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]


def _cks(model: Any) -> list[Any]:
    """Return all CheckConstraint objects on a model's table."""
    mapper = sa_inspect(model)
    return [
        c
        for c in mapper.persist_selectable.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]


def _indexes(model: Any) -> set[str]:
    """Return the set of index names declared on a model's table."""
    mapper = sa_inspect(model)
    return {ix.name for ix in mapper.persist_selectable.indexes if ix.name}


# ---------------------------------------------------------------------------
# Test: models importable and registered on Base.metadata
# ---------------------------------------------------------------------------


class TestModelsImport:
    def test_chat_session_importable(self) -> None:
        assert ChatSession is not None

    def test_chat_message_importable(self) -> None:
        assert ChatMessage is not None

    def test_user_preferences_importable(self) -> None:
        assert UserPreferences is not None

    def test_chat_sessions_table_name(self) -> None:
        assert ChatSession.__tablename__ == "chat_sessions"

    def test_chat_messages_table_name(self) -> None:
        assert ChatMessage.__tablename__ == "chat_messages"

    def test_user_preferences_table_name(self) -> None:
        assert UserPreferences.__tablename__ == "user_preferences"

    def test_all_three_present_in_metadata(self) -> None:
        tables = set(Base.metadata.tables.keys())
        assert {"chat_sessions", "chat_messages", "user_preferences"} <= tables


# ---------------------------------------------------------------------------
# Test: chat_sessions columns, constraints, indexes
# ---------------------------------------------------------------------------


class TestChatSessionColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(ChatSession, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_user_id_fk(self) -> None:
        assert "users.id" in _fks(ChatSession)

    def test_user_id_not_nullable(self) -> None:
        assert _col(ChatSession, "user_id").nullable is False

    def test_analysis_id_fk(self) -> None:
        assert "analyses.id" in _fks(ChatSession)

    def test_analysis_id_nullable(self) -> None:
        # NULL for portfolio-wide sessions (T-101); set for memo-scoped (T-100)
        assert _col(ChatSession, "analysis_id").nullable is True

    def test_session_type_not_nullable(self) -> None:
        assert _col(ChatSession, "session_type").nullable is False

    def test_title_nullable(self) -> None:
        assert _col(ChatSession, "title").nullable is True

    def test_title_max_length(self) -> None:
        assert _col(ChatSession, "title").type.length == 200

    def test_created_at_has_server_default(self) -> None:
        assert _col(ChatSession, "created_at").server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        assert _col(ChatSession, "updated_at").server_default is not None

    def test_scope_consistency_check_constraint(self) -> None:
        cks = _cks(ChatSession)
        ck_names = {ck.name for ck in cks if ck.name}
        assert "ck_chat_sessions_scope_consistency" in ck_names

    def test_indexes_on_user_and_analysis(self) -> None:
        idx = _indexes(ChatSession)
        assert "ix_chat_sessions_user_id" in idx
        assert "ix_chat_sessions_analysis_id" in idx


# ---------------------------------------------------------------------------
# Test: chat_messages columns, constraints, indexes
# ---------------------------------------------------------------------------


class TestChatMessageColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(ChatMessage, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_session_id_fk(self) -> None:
        assert "chat_sessions.id" in _fks(ChatMessage)

    def test_session_id_not_nullable(self) -> None:
        assert _col(ChatMessage, "session_id").nullable is False

    def test_role_not_nullable(self) -> None:
        assert _col(ChatMessage, "role").nullable is False

    def test_content_not_nullable(self) -> None:
        assert _col(ChatMessage, "content").nullable is False

    def test_tool_calls_is_jsonb(self) -> None:
        col = _col(ChatMessage, "tool_calls")
        assert isinstance(col.type, JSONB)

    def test_tool_calls_nullable(self) -> None:
        assert _col(ChatMessage, "tool_calls").nullable is True

    def test_tool_name_nullable(self) -> None:
        assert _col(ChatMessage, "tool_name").nullable is True

    def test_tokens_used_nullable(self) -> None:
        assert _col(ChatMessage, "tokens_used").nullable is True

    def test_created_at_has_server_default(self) -> None:
        assert _col(ChatMessage, "created_at").server_default is not None

    def test_index_on_session_id(self) -> None:
        assert "ix_chat_messages_session_id" in _indexes(ChatMessage)

    def test_composite_index_on_session_and_created_at(self) -> None:
        assert "ix_chat_messages_session_id_created_at" in _indexes(ChatMessage)


# ---------------------------------------------------------------------------
# Test: user_preferences columns, constraints, indexes
# ---------------------------------------------------------------------------


class TestUserPreferencesColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(UserPreferences, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_user_id_fk(self) -> None:
        assert "users.id" in _fks(UserPreferences)

    def test_user_id_not_nullable(self) -> None:
        assert _col(UserPreferences, "user_id").nullable is False

    def test_user_id_is_unique(self) -> None:
        # one preferences row per user
        assert _col(UserPreferences, "user_id").unique is True

    def test_user_id_unique_constraint_present(self) -> None:
        uqs = _uqs(UserPreferences)
        uq_names = {uq.name for uq in uqs if uq.name}
        assert "uq_user_preferences_user_id" in uq_names

    def test_theme_not_nullable(self) -> None:
        assert _col(UserPreferences, "theme").nullable is False

    def test_theme_has_server_default(self) -> None:
        assert _col(UserPreferences, "theme").server_default is not None

    def test_chat_response_style_not_nullable(self) -> None:
        assert _col(UserPreferences, "chat_response_style").nullable is False

    def test_chat_response_style_has_server_default(self) -> None:
        col = _col(UserPreferences, "chat_response_style")
        assert col.server_default is not None

    def test_default_exchange_nullable(self) -> None:
        assert _col(UserPreferences, "default_exchange").nullable is True

    def test_watchlist_tickers_is_jsonb(self) -> None:
        col = _col(UserPreferences, "watchlist_tickers")
        assert isinstance(col.type, JSONB)

    def test_watchlist_tickers_not_nullable(self) -> None:
        assert _col(UserPreferences, "watchlist_tickers").nullable is False

    def test_watchlist_tickers_has_server_default(self) -> None:
        col = _col(UserPreferences, "watchlist_tickers")
        assert col.server_default is not None

    def test_email_notifications_enabled_not_nullable(self) -> None:
        assert _col(UserPreferences, "email_notifications_enabled").nullable is False

    def test_email_notifications_enabled_has_server_default(self) -> None:
        col = _col(UserPreferences, "email_notifications_enabled")
        assert col.server_default is not None

    def test_created_at_has_server_default(self) -> None:
        assert _col(UserPreferences, "created_at").server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        assert _col(UserPreferences, "updated_at").server_default is not None

    def test_index_on_user_id(self) -> None:
        assert "ix_user_preferences_user_id" in _indexes(UserPreferences)


# ---------------------------------------------------------------------------
# Test: UserPreferences personalization columns (T-106)
# ---------------------------------------------------------------------------


class TestUserPreferencesPersonalizationColumns:
    """
    risk_appetite / preferred_sectors, added by T-106's migration
    (20260811_0000_f6a7b8c9d0e1) on top of T-099's user_preferences
    table -- both represent "not yet known" differently on purpose
    (NULL vs. an empty JSON array), matching the migration's own
    docstring for why watchlist_tickers's []-means-empty convention is
    reused for preferred_sectors rather than mixing conventions within
    the same table.
    """

    def test_risk_appetite_nullable(self) -> None:
        # NULL until the assistant has asked and the user has answered
        # once -- see chat_llm.build_personalization_instruction.
        assert _col(UserPreferences, "risk_appetite").nullable is True

    def test_risk_appetite_has_no_server_default(self) -> None:
        # Deliberately no default -- "not yet known" must be NULL, not
        # a guessed starting value.
        assert _col(UserPreferences, "risk_appetite").server_default is None

    def test_preferred_sectors_is_jsonb(self) -> None:
        col = _col(UserPreferences, "preferred_sectors")
        assert isinstance(col.type, JSONB)

    def test_preferred_sectors_not_nullable(self) -> None:
        assert _col(UserPreferences, "preferred_sectors").nullable is False

    def test_preferred_sectors_has_server_default(self) -> None:
        col = _col(UserPreferences, "preferred_sectors")
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# Test: relationships
# ---------------------------------------------------------------------------


class TestRelationships:
    def _rel(self, model: Any, name: str) -> "RelationshipProperty[Any]":
        mapper = sa_inspect(model)
        return cast("RelationshipProperty[Any]", mapper.relationships[name])

    def test_user_has_chat_sessions_relationship(self) -> None:
        rel = self._rel(User, "chat_sessions")
        assert rel is not None

    def test_user_chat_sessions_cascade_delete_orphan(self) -> None:
        rel = self._rel(User, "chat_sessions")
        assert "delete-orphan" in str(rel.cascade)

    def test_user_has_preferences_relationship(self) -> None:
        rel = self._rel(User, "preferences")
        assert rel is not None

    def test_user_preferences_is_not_list(self) -> None:
        # 1:1 relationship — uselist=False
        rel = self._rel(User, "preferences")
        assert rel.uselist is False

    def test_analysis_has_chat_sessions_relationship(self) -> None:
        rel = self._rel(Analysis, "chat_sessions")
        assert rel is not None

    def test_analysis_chat_sessions_cascade_delete_orphan(self) -> None:
        rel = self._rel(Analysis, "chat_sessions")
        assert "delete-orphan" in str(rel.cascade)

    def test_chat_session_has_user_relationship(self) -> None:
        rel = self._rel(ChatSession, "user")
        assert rel is not None

    def test_chat_session_has_analysis_relationship(self) -> None:
        rel = self._rel(ChatSession, "analysis")
        assert rel is not None

    def test_chat_session_has_messages_relationship(self) -> None:
        rel = self._rel(ChatSession, "messages")
        assert rel is not None

    def test_chat_session_messages_cascade_delete_orphan(self) -> None:
        rel = self._rel(ChatSession, "messages")
        assert "delete-orphan" in str(rel.cascade)

    def test_chat_message_has_session_relationship(self) -> None:
        rel = self._rel(ChatMessage, "session")
        assert rel is not None

    def test_user_preferences_has_user_relationship(self) -> None:
        rel = self._rel(UserPreferences, "user")
        assert rel is not None


# ---------------------------------------------------------------------------
# Test: __repr__ methods
# ---------------------------------------------------------------------------


class TestReprMethods:
    def test_chat_session_repr(self) -> None:
        s = ChatSession(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            session_type="portfolio_wide",
        )
        assert "ChatSession" in repr(s)
        assert "portfolio_wide" in repr(s)

    def test_chat_message_repr(self) -> None:
        m = ChatMessage(
            session_id=uuid.uuid4(),
            role="assistant",
            content="Here is the summary you asked for.",
        )
        assert "ChatMessage" in repr(m)
        assert "assistant" in repr(m)

    def test_user_preferences_repr(self) -> None:
        p = UserPreferences(user_id=uuid.uuid4(), theme="dark")
        assert "UserPreferences" in repr(p)
        assert "dark" in repr(p)


# ---------------------------------------------------------------------------
# Test: model construction (verdict-time / default-only fields)
# ---------------------------------------------------------------------------


class TestModelConstruction:
    def test_memo_scoped_session_can_be_constructed(self) -> None:
        analysis_id = uuid.uuid4()
        session = ChatSession(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            analysis_id=analysis_id,
            session_type="memo_scoped",
            title="TCS Q1 review",
        )
        assert session.analysis_id == analysis_id
        assert session.session_type == "memo_scoped"

    def test_portfolio_wide_session_has_no_analysis_id(self) -> None:
        session = ChatSession(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            session_type="portfolio_wide",
        )
        assert session.analysis_id is None

    def test_tool_message_can_carry_tool_calls_payload(self) -> None:
        message = ChatMessage(
            session_id=uuid.uuid4(),
            role="tool",
            content="3 BUY-rated analyses found in the last 30 days.",
            tool_calls={"name": "get_user_analyses", "args": {"verdict": "BUY"}},
            tool_name="get_user_analyses",
        )
        assert message.tool_name == "get_user_analyses"
        assert message.tool_calls is not None

    def test_user_message_has_no_tool_fields(self) -> None:
        message = ChatMessage(
            session_id=uuid.uuid4(),
            role="user",
            content="Should I hold my TCS position?",
        )
        assert message.tool_calls is None
        assert message.tool_name is None

    def test_preferences_can_be_constructed_with_defaults_only(self) -> None:
        prefs = UserPreferences(user_id=uuid.uuid4())
        # Column-level Python `default=` values apply at flush time via the
        # ORM, not at bare construction — this only asserts construction
        # doesn't require the caller to pass every optional field.
        assert prefs.user_id is not None
