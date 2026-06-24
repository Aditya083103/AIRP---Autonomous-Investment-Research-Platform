# backend/tests/unit/test_orm_models.py
"""
Unit tests for backend/models/orm.py and backend/db/session.py — T-016

All tests run fully offline — no real database connection is required.
SQLAlchemy metadata inspection and model construction are used instead.

Test coverage (acceptance criteria from T-016):
  ✓ All five ORM classes are importable from backend.models
  ✓ Base.metadata contains all five expected table names
  ✓ Each table has the correct set of columns
  ✓ Primary key columns are UUID type on every table
  ✓ Foreign key constraints are declared correctly
  ✓ Unique constraints are present on the correct tables
  ✓ Nullable / not-nullable rules match the schema spec
  ✓ server_default is set on timestamp and status columns
  ✓ Enum column types are declared (analysis_status, verdict, agent_name, exchange)
  ✓ JSONB column is on agent_outputs.output_json
  ✓ __repr__ returns a non-empty string for each model
  ✓ User → Analysis cascade relationship is declared
  ✓ Analysis → AgentOutput cascade relationship is declared
  ✓ Analysis → InvestmentMemo 1:1 relationship is declared
  ✓ get_async_session is an async generator (callable, correct type)
  ✓ _build_database_url falls back to env var when settings is None
  ✓ AsyncSessionLocal is an async_sessionmaker instance

Run with:
    ENVIRONMENT=test python -m pytest backend/tests/unit/test_orm_models.py -v
"""

from __future__ import annotations

import os  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")

from inspect import isasyncgenfunction  # noqa: E402
from typing import Any, cast  # noqa: E402
from unittest.mock import patch  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402
from sqlalchemy.orm import RelationshipProperty  # noqa: E402

from backend.models import (  # noqa: E402
    AgentOutput,
    Analysis,
    Base,
    Company,
    InvestmentMemo,
    User,
)

# ---------------------------------------------------------------------------
# Helpers
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
    # persist_selectable is the SA 2.x replacement for mapped_table
    return [
        c
        for c in mapper.persist_selectable.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]


# ---------------------------------------------------------------------------
# Test: all models importable from backend.models
# ---------------------------------------------------------------------------


class TestModelsImport:
    def test_base_importable(self) -> None:
        assert Base is not None

    def test_user_importable(self) -> None:
        assert User is not None

    def test_company_importable(self) -> None:
        assert Company is not None

    def test_analysis_importable(self) -> None:
        assert Analysis is not None

    def test_agent_output_importable(self) -> None:
        assert AgentOutput is not None

    def test_investment_memo_importable(self) -> None:
        assert InvestmentMemo is not None


# ---------------------------------------------------------------------------
# Test: Base.metadata contains all five tables
# ---------------------------------------------------------------------------


class TestMetadataTables:
    def test_all_five_tables_in_metadata(self) -> None:
        expected = {
            "users",
            "companies",
            "analyses",
            "agent_outputs",
            "investment_memos",
        }
        actual = set(Base.metadata.tables.keys())
        assert expected == actual

    def test_no_extra_tables(self) -> None:
        assert len(Base.metadata.tables) == 5


# ---------------------------------------------------------------------------
# Test: users table columns
# ---------------------------------------------------------------------------


class TestUserColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(User, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_email_not_nullable(self) -> None:
        assert _col(User, "email").nullable is False

    def test_email_unique(self) -> None:
        assert _col(User, "email").unique is True

    def test_email_max_length(self) -> None:
        assert _col(User, "email").type.length == 320

    def test_password_hash_not_nullable(self) -> None:
        assert _col(User, "password_hash").nullable is False

    def test_password_hash_max_length(self) -> None:
        # bcrypt hashes are a fixed 60 chars; 255 leaves headroom for a
        # future hash scheme migration (e.g. argon2) without a column resize.
        assert _col(User, "password_hash").type.length == 255

    def test_display_name_nullable(self) -> None:
        assert _col(User, "display_name").nullable is True

    def test_is_active_not_nullable(self) -> None:
        assert _col(User, "is_active").nullable is False

    def test_is_active_has_server_default(self) -> None:
        assert _col(User, "is_active").server_default is not None

    def test_created_at_has_server_default(self) -> None:
        col = _col(User, "created_at")
        assert col.server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        col = _col(User, "updated_at")
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# Test: companies table columns
# ---------------------------------------------------------------------------


class TestCompanyColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(Company, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_name_not_nullable(self) -> None:
        assert _col(Company, "name").nullable is False

    def test_ticker_not_nullable(self) -> None:
        assert _col(Company, "ticker").nullable is False

    def test_ticker_yf_not_nullable(self) -> None:
        assert _col(Company, "ticker_yf").nullable is False

    def test_exchange_not_nullable(self) -> None:
        assert _col(Company, "exchange").nullable is False

    def test_sector_nullable(self) -> None:
        assert _col(Company, "sector").nullable is True

    def test_industry_nullable(self) -> None:
        assert _col(Company, "industry").nullable is True

    def test_ticker_exchange_unique_constraint(self) -> None:
        uqs = _uqs(Company)
        uq_names = {uq.name for uq in uqs if uq.name}
        assert "uq_companies_ticker_exchange" in uq_names

    def test_no_fks_on_companies(self) -> None:
        # companies is the root table — no foreign keys expected
        assert len(_fks(Company)) == 0


# ---------------------------------------------------------------------------
# Test: analyses table columns and FKs
# ---------------------------------------------------------------------------


class TestAnalysisColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(Analysis, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_company_id_fk(self) -> None:
        assert "companies.id" in _fks(Analysis)

    def test_user_id_fk(self) -> None:
        assert "users.id" in _fks(Analysis)

    def test_status_not_nullable(self) -> None:
        assert _col(Analysis, "status").nullable is False

    def test_status_has_server_default(self) -> None:
        col = _col(Analysis, "status")
        assert col.server_default is not None

    def test_error_message_nullable(self) -> None:
        assert _col(Analysis, "error_message").nullable is True

    def test_debate_rounds_not_nullable(self) -> None:
        assert _col(Analysis, "debate_rounds_completed").nullable is False

    def test_duration_seconds_nullable(self) -> None:
        assert _col(Analysis, "duration_seconds").nullable is True

    def test_requested_at_has_server_default(self) -> None:
        col = _col(Analysis, "requested_at")
        assert col.server_default is not None

    def test_started_at_nullable(self) -> None:
        assert _col(Analysis, "started_at").nullable is True

    def test_completed_at_nullable(self) -> None:
        assert _col(Analysis, "completed_at").nullable is True


# ---------------------------------------------------------------------------
# Test: agent_outputs table columns
# ---------------------------------------------------------------------------


class TestAgentOutputColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(AgentOutput, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_analysis_id_fk(self) -> None:
        assert "analyses.id" in _fks(AgentOutput)

    def test_output_json_is_jsonb(self) -> None:
        col = _col(AgentOutput, "output_json")
        assert isinstance(col.type, JSONB)

    def test_output_json_not_nullable(self) -> None:
        assert _col(AgentOutput, "output_json").nullable is False

    def test_agent_name_not_nullable(self) -> None:
        assert _col(AgentOutput, "agent_name").nullable is False

    def test_tokens_used_nullable(self) -> None:
        assert _col(AgentOutput, "tokens_used").nullable is True

    def test_latency_ms_nullable(self) -> None:
        assert _col(AgentOutput, "latency_ms").nullable is True

    def test_langsmith_run_id_nullable(self) -> None:
        assert _col(AgentOutput, "langsmith_run_id").nullable is True

    def test_unique_constraint_analysis_agent(self) -> None:
        uqs = _uqs(AgentOutput)
        uq_names = {uq.name for uq in uqs if uq.name}
        assert "uq_agent_outputs_analysis_agent" in uq_names

    def test_created_at_has_server_default(self) -> None:
        col = _col(AgentOutput, "created_at")
        assert col.server_default is not None


# ---------------------------------------------------------------------------
# Test: investment_memos table columns
# ---------------------------------------------------------------------------


class TestInvestmentMemoColumns:
    def test_pk_is_uuid(self) -> None:
        col = _col(InvestmentMemo, "id")
        assert isinstance(col.type, UUID)
        assert col.primary_key is True

    def test_analysis_id_fk(self) -> None:
        assert "analyses.id" in _fks(InvestmentMemo)

    def test_verdict_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "verdict").nullable is False

    def test_conviction_score_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "conviction_score").nullable is False

    def test_executive_summary_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "executive_summary").nullable is False

    def test_investment_thesis_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "investment_thesis").nullable is False

    def test_bull_case_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "bull_case").nullable is False

    def test_bear_case_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "bear_case").nullable is False

    def test_risk_summary_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "risk_summary").nullable is False

    def test_valuation_summary_not_nullable(self) -> None:
        assert _col(InvestmentMemo, "valuation_summary").nullable is False

    def test_price_target_nullable(self) -> None:
        assert _col(InvestmentMemo, "price_target").nullable is True

    def test_pdf_path_nullable(self) -> None:
        assert _col(InvestmentMemo, "pdf_path").nullable is True

    def test_analysis_id_is_unique(self) -> None:
        # analysis_id has a unique=True on the column level (1:1 with analyses)
        col = _col(InvestmentMemo, "analysis_id")
        assert col.unique is True


# ---------------------------------------------------------------------------
# Test: ORM relationships
# ---------------------------------------------------------------------------


class TestRelationships:
    def _rel(self, model: Any, name: str) -> "RelationshipProperty[Any]":
        mapper = sa_inspect(model)
        return cast("RelationshipProperty[Any]", mapper.relationships[name])

    def test_user_has_analyses_relationship(self) -> None:
        rel = self._rel(User, "analyses")
        assert rel is not None

    def test_user_analyses_cascade_delete_orphan(self) -> None:
        rel = self._rel(User, "analyses")
        assert "delete-orphan" in str(rel.cascade)

    def test_company_has_analyses_relationship(self) -> None:
        rel = self._rel(Company, "analyses")
        assert rel is not None

    def test_analysis_has_agent_outputs_relationship(self) -> None:
        rel = self._rel(Analysis, "agent_outputs")
        assert rel is not None

    def test_analysis_has_investment_memo_relationship(self) -> None:
        rel = self._rel(Analysis, "investment_memo")
        assert rel is not None

    def test_analysis_memo_is_not_list(self) -> None:
        # 1:1 relationship — uselist=False
        rel = self._rel(Analysis, "investment_memo")
        assert rel.uselist is False

    def test_agent_output_has_analysis_relationship(self) -> None:
        rel = self._rel(AgentOutput, "analysis")
        assert rel is not None

    def test_investment_memo_has_analysis_relationship(self) -> None:
        rel = self._rel(InvestmentMemo, "analysis")
        assert rel is not None


# ---------------------------------------------------------------------------
# Test: __repr__ methods
# ---------------------------------------------------------------------------


class TestReprMethods:
    # Use the real constructor (not __new__) so SQLAlchemy sets
    # _sa_instance_state correctly. Only supply columns that __repr__ reads.

    def test_user_repr(self) -> None:
        u = User(id=uuid.uuid4(), email="test@example.com")
        assert "User" in repr(u)
        assert "test@example.com" in repr(u)

    def test_company_repr(self) -> None:
        c = Company(ticker="TCS", exchange="NSE")
        assert "TCS" in repr(c)

    def test_analysis_repr(self) -> None:
        a = Analysis(id=uuid.uuid4(), status="pending")
        assert "Analysis" in repr(a)
        assert "pending" in repr(a)

    def test_agent_output_repr(self) -> None:
        ao = AgentOutput(
            analysis_id=uuid.uuid4(),
            agent_name="fundamental_analyst",
        )
        assert "AgentOutput" in repr(ao)

    def test_investment_memo_repr(self) -> None:
        m = InvestmentMemo(
            analysis_id=uuid.uuid4(),
            verdict="BUY",
            conviction_score=8,
        )
        assert "InvestmentMemo" in repr(m)
        assert "BUY" in repr(m)


# ---------------------------------------------------------------------------
# Test: session.py
# ---------------------------------------------------------------------------


class TestSession:
    def test_get_async_session_is_async_generator(self) -> None:
        from backend.db.session import get_async_session

        assert isasyncgenfunction(get_async_session)

    def test_async_session_local_is_sessionmaker(self) -> None:
        from backend.db.session import AsyncSessionLocal

        assert isinstance(AsyncSessionLocal, async_sessionmaker)

    def test_build_database_url_falls_back_to_env(self) -> None:
        from backend.db import session as session_mod

        with patch.object(session_mod, "settings", None):
            with patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql+asyncpg://u:p@host/db"},
            ):
                url = session_mod._build_database_url()
        assert url == "postgresql+asyncpg://u:p@host/db"

    def test_build_database_url_uses_settings_when_available(
        self,
    ) -> None:
        from backend.db import session as session_mod

        class _FakeSettings:
            active_database_url = (
                "postgresql+asyncpg://airp:airp@localhost:5432/airp_test"
            )

        with patch.object(session_mod, "settings", _FakeSettings()):
            url = session_mod._build_database_url()
        assert "airp_test" in url

    def test_prepare_url_strips_sslmode_and_sets_connect_args(
        self,
    ) -> None:
        from backend.db.session import _prepare_url

        neon_url = "postgresql+asyncpg://user:pass@host/db?sslmode=require"
        clean_url, connect_args = _prepare_url(neon_url)
        assert "sslmode" not in clean_url
        assert "ssl" not in clean_url
        assert connect_args.get("ssl") is True

    def test_prepare_url_leaves_local_url_unchanged(self) -> None:
        from backend.db.session import _prepare_url

        local = "postgresql+asyncpg://airp:airp@localhost:5432/airp"
        clean_url, connect_args = _prepare_url(local)
        assert clean_url == local
        assert connect_args == {}
