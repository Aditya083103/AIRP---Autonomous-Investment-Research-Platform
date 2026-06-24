# backend/tests/unit/test_analysis_service.py
"""
Unit tests for T-047: backend/services/analysis.py

Test strategy
-------------
1. resolve_company()
     ticker_override path             -- uses override directly
     bare ticker with exchange suffix -- 'TCS.NS' / 'INFY.BO' recognised
     known company name (override table, case-insensitive)
     unknown bare symbol fallback     -- 'WIPRO' -> 'WIPRO.NS'
     unknown free-text fallback       -- spaces stripped, upper-cased
     exchange_override is honoured / invalid value falls back to default
2. get_or_create_company()
     existing row found  -- returns it, no INSERT
     no existing row     -- inserts, commits, refreshes, returns new row
3. create_analysis_job()
     inserts an Analysis row with status='pending', returns it with id set
4. run_analysis_pipeline()
     success path -- builds InvestmentState, invokes the graph via a
                     mocked _invoke_graph_sync (patched module-level),
                     never touches StatePersistenceService.mark_failed
     failure path -- graph invocation raises -> mark_failed is called
                     with the job_id and the exception message
     never raises -- even when mark_failed itself raises, the coroutine
                     completes without propagating

All database interactions use mocked AsyncSession objects (AsyncMock /
MagicMock) -- no real PostgreSQL connection, matching the existing
test_state_persistence.py / test_dependencies_auth.py pattern.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from backend.models.orm import Analysis, Company
from backend.services.analysis import (
    TickerResolution,
    create_analysis_job,
    get_or_create_company,
    resolve_company,
    run_analysis_pipeline,
)

# ---------------------------------------------------------------------------
# resolve_company()
# ---------------------------------------------------------------------------


class TestResolveCompanyTickerOverride:
    def test_ticker_override_used_directly(self) -> None:
        result = resolve_company("Tata Consultancy Services", ticker_override="TCS")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"

    def test_ticker_override_with_existing_suffix_is_normalised(self) -> None:
        result = resolve_company("Infosys", ticker_override="INFY.NS")
        assert result.ticker == "INFY.NS"

    def test_ticker_override_with_exchange_override(self) -> None:
        result = resolve_company(
            "Reliance", ticker_override="RELIANCE", exchange_override="BSE"
        )
        assert result.ticker == "RELIANCE.BO"
        assert result.exchange == "BSE"

    def test_company_name_preserved_as_typed(self) -> None:
        result = resolve_company("Tata Consultancy Services", ticker_override="TCS")
        assert result.company_name == "Tata Consultancy Services"


class TestResolveCompanyExplicitSuffix:
    def test_nse_suffix_recognised(self) -> None:
        result = resolve_company("TCS.NS")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"

    def test_bse_suffix_recognised(self) -> None:
        result = resolve_company("INFY.BO")
        assert result.ticker == "INFY.BO"
        assert result.exchange == "BSE"

    def test_suffix_is_case_insensitive(self) -> None:
        result = resolve_company("tcs.ns")
        assert result.ticker == "TCS.NS"
        assert result.exchange == "NSE"


class TestResolveCompanyNameOverrideTable:
    @pytest.mark.parametrize(
        "company_name,expected_bare",
        [
            ("Tata Consultancy Services", "TCS"),
            ("Infosys", "INFY"),
            ("Infosys Limited", "INFY"),
            ("Reliance Industries", "RELIANCE"),
            ("HDFC Bank", "HDFCBANK"),
            ("ICICI Bank", "ICICIBANK"),
            ("State Bank of India", "SBIN"),
            ("Wipro", "WIPRO"),
        ],
    )
    def test_known_company_name_resolves_to_expected_ticker(
        self, company_name: str, expected_bare: str
    ) -> None:
        result = resolve_company(company_name)
        assert result.ticker == f"{expected_bare}.NS"

    def test_lookup_is_case_insensitive(self) -> None:
        result = resolve_company("TATA CONSULTANCY SERVICES")
        assert result.ticker == "TCS.NS"

    def test_lookup_ignores_surrounding_whitespace(self) -> None:
        result = resolve_company("  Infosys  ")
        assert result.ticker == "INFY.NS"


class TestResolveCompanyFallback:
    def test_unknown_bare_symbol_gets_default_exchange_suffix(self) -> None:
        result = resolve_company("WIPRO")
        assert result.ticker == "WIPRO.NS"
        assert result.exchange == "NSE"

    def test_unknown_free_text_strips_spaces_and_upper_cases(self) -> None:
        result = resolve_company("Some New Company")
        assert result.ticker == "SOMENEWCOMPANY.NS"

    def test_exchange_override_changes_default_suffix(self) -> None:
        result = resolve_company("WIPRO", exchange_override="BSE")
        assert result.ticker == "WIPRO.BO"
        assert result.exchange == "BSE"

    def test_invalid_exchange_override_falls_back_to_default(self) -> None:
        result = resolve_company("WIPRO", exchange_override="NYSE")
        assert result.exchange == "NSE"
        assert result.ticker == "WIPRO.NS"


# ---------------------------------------------------------------------------
# get_or_create_company()
# ---------------------------------------------------------------------------


def _make_session_returning_company(company: Company | None) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=company)
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


class TestGetOrCreateCompany:
    @pytest.mark.asyncio
    async def test_returns_existing_company_without_inserting(self) -> None:
        existing = Company(
            id=uuid.uuid4(),
            name="Tata Consultancy Services",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        session = _make_session_returning_company(existing)
        resolution = TickerResolution(
            company_name="TCS", ticker="TCS.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        assert result is existing
        session.add.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_company_when_none_exists(self) -> None:
        session = _make_session_returning_company(None)
        resolution = TickerResolution(
            company_name="Wipro", ticker="WIPRO.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert result.ticker == "WIPRO"
        assert result.ticker_yf == "WIPRO.NS"
        assert result.exchange == "NSE"

    @pytest.mark.asyncio
    async def test_new_company_uses_bare_ticker_without_suffix(self) -> None:
        session = _make_session_returning_company(None)
        resolution = TickerResolution(
            company_name="Infosys", ticker="INFY.NS", exchange="NSE"
        )

        result = await get_or_create_company(session, resolution)

        assert result.ticker == "INFY"


# ---------------------------------------------------------------------------
# create_analysis_job()
# ---------------------------------------------------------------------------


class TestCreateAnalysisJob:
    @pytest.mark.asyncio
    async def test_inserts_analysis_with_pending_status(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        company = Company(
            id=uuid.uuid4(),
            name="TCS",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        user_id = uuid.uuid4()

        async def _fake_refresh(instance: Any) -> None:
            instance.id = uuid.uuid4()
            instance.status = "pending"

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        result = await create_analysis_job(session, company=company, user_id=user_id)

        assert isinstance(result, Analysis)
        assert result.status == "pending"
        assert result.id is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_links_analysis_to_correct_company_and_user(self) -> None:
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        company = Company(
            id=uuid.uuid4(),
            name="TCS",
            ticker="TCS",
            ticker_yf="TCS.NS",
            exchange="NSE",
        )
        user_id = uuid.uuid4()

        result = await create_analysis_job(session, company=company, user_id=user_id)

        assert result.company_id == company.id
        assert result.user_id == user_id


# ---------------------------------------------------------------------------
# run_analysis_pipeline()
# ---------------------------------------------------------------------------


class TestRunAnalysisPipelineSuccess:
    @pytest.mark.asyncio
    async def test_invokes_graph_with_initial_state(self) -> None:
        job_id = uuid.uuid4()
        with (
            patch("backend.services.analysis._invoke_graph_sync") as mock_invoke,
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_invoke.return_value = {"status": "completed"}

            await run_analysis_pipeline(
                job_id=job_id,
                company_name="Tata Consultancy Services",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )

            mock_invoke.assert_called_once()
            called_state = mock_invoke.call_args.args[0]
            assert called_state["job_id"] == str(job_id)
            assert called_state["ticker"] == "TCS.NS"
            assert called_state["company_name"] == "Tata Consultancy Services"
            mock_svc_cls.return_value.mark_failed.assert_not_called()


class TestRunAnalysisPipelineFailure:
    @pytest.mark.asyncio
    async def test_marks_job_failed_when_graph_raises(self) -> None:
        job_id = uuid.uuid4()
        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "backend.services.analysis._invoke_graph_sync",
                side_effect=RuntimeError("boom"),
            ),
            patch("backend.db.session.AsyncSessionLocal", mock_session_local),
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_svc_cls.return_value.mark_failed = AsyncMock()

            await run_analysis_pipeline(
                job_id=job_id,
                company_name="TCS",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )

            mock_svc_cls.return_value.mark_failed.assert_awaited_once()
            _, kwargs = mock_svc_cls.return_value.mark_failed.call_args
            assert kwargs["job_id"] == str(job_id)
            assert "boom" in kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_never_raises_when_mark_failed_itself_raises(self) -> None:
        job_id = uuid.uuid4()
        mock_session_local = MagicMock()
        mock_session_local.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_local.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "backend.services.analysis._invoke_graph_sync",
                side_effect=RuntimeError("graph exploded"),
            ),
            patch("backend.db.session.AsyncSessionLocal", mock_session_local),
            patch(
                "backend.services.state_persistence.StatePersistenceService"
            ) as mock_svc_cls,
        ):
            mock_svc_cls.return_value.mark_failed = AsyncMock(
                side_effect=RuntimeError("db also exploded")
            )

            # Must complete without raising -- this call itself is the
            # assertion; pytest fails the test if an exception escapes.
            await run_analysis_pipeline(
                job_id=job_id,
                company_name="TCS",
                ticker="TCS.NS",
                exchange="NSE",
                requested_by="user-123",
            )
