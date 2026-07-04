# backend/tests/unit/test_analysis_charts_service.py
"""
Unit tests for T-062: backend/services/analysis.py's
get_analysis_chart_data, _fetch_price_history_sync, and
_fetch_financial_trend_sync.

A separate file from test_analysis_result_history_service.py -- same
"new task, own test file" decision that file's own docstring already
explains, extended to T-062. test_analysis_charts_router.py (this
directory) covers the same feature end-to-end through the FastAPI app
by monkeypatching _fetch_price_history_sync/_fetch_financial_trend_sync
directly; this file instead unit-tests those two functions themselves
(mocking fetch_ohlcv.invoke/fetch_income_statement.invoke, one level
further down) plus get_analysis_chart_data's DB/ownership/status logic
in isolation with a mocked AsyncSession -- no real PostgreSQL
connection and no real yFinance call, matching the existing
test_analysis_result_history_service.py pattern throughout.

Test strategy
-------------
1. _fetch_price_history_sync()
     fetch_ohlcv succeeds        -- returns (points, currency, None)
     fetch_ohlcv returns 'error' -- returns ([], "INR", <warning str>)
2. _fetch_financial_trend_sync()
     fetch_income_statement succeeds        -- returns (points, None)
     fetch_income_statement returns 'error' -- returns ([], <warning>)
3. get_analysis_chart_data()
     no row for job_id                   -- returns None
     row belongs to a different user     -- returns None (never 403)
     status='pending'/'running'/'failed' -- raises AnalysisNotReadyError
     status='completed', snapshot NULL   -- raises AnalysisNotReadyError
     status='completed', snapshot has no ticker -- raises
       AnalysisNotReadyError (defensive fallback, not a 500)
     status='completed', valid snapshot  -- returns AnalysisChartData
       with valuation/sentiment/risk passed through unchanged and
       price_history/financials from the (mocked) live fetch
     valuation/sentiment/risk missing from snapshot individually --
       that field is None and a matching entry lands in data_warnings,
       independent of the other four sources

ENVIRONMENT must be set to 'test' before any backend import.
"""

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from backend.services.analysis import (
    AnalysisNotReadyError,
    _fetch_financial_trend_sync,
    _fetch_price_history_sync,
    get_analysis_chart_data,
)

# ---------------------------------------------------------------------------
# _fetch_price_history_sync() / _fetch_financial_trend_sync()
# ---------------------------------------------------------------------------


class TestFetchPriceHistorySync:
    def test_success_returns_points_and_currency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_result = {
            "ticker": "TCS.NS",
            "period": "1y",
            "currency": "INR",
            "data_points": 2,
            "ohlcv": [
                {
                    "date": "2026-06-18",
                    "open": 3800.0,
                    "high": 3850.0,
                    "low": 3790.0,
                    "close": 3845.2,
                    "volume": 1_204_500,
                },
            ],
        }
        monkeypatch.setattr(
            "backend.services.analysis.fetch_ohlcv",
            MagicMock(invoke=MagicMock(return_value=fake_result)),
        )

        points, currency, warning = _fetch_price_history_sync("TCS.NS")

        assert points == [{"date": "2026-06-18", "close": 3845.2, "volume": 1_204_500}]
        assert currency == "INR"
        assert warning is None

    def test_error_returns_empty_list_and_a_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_result = {
            "error": "ticker_not_found",
            "ticker": "BADTICKER.NS",
            "message": "No price data found for ticker 'BADTICKER.NS'.",
        }
        monkeypatch.setattr(
            "backend.services.analysis.fetch_ohlcv",
            MagicMock(invoke=MagicMock(return_value=fake_result)),
        )

        points, currency, warning = _fetch_price_history_sync("BADTICKER.NS")

        assert points == []
        assert currency == "INR"
        assert warning is not None
        assert "No price data found" in warning


class TestFetchFinancialTrendSync:
    def test_success_returns_points(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_result = {
            "ticker": "TCS.NS",
            "income_statement": [
                {
                    "fiscal_year": "FY 2024",
                    "revenue_crores": 240_890.5,
                    "net_income_crores": 45_868.0,
                },
            ],
        }
        monkeypatch.setattr(
            "backend.services.analysis.fetch_income_statement",
            MagicMock(invoke=MagicMock(return_value=fake_result)),
        )

        points, warning = _fetch_financial_trend_sync("TCS.NS")

        assert points == [
            {
                "fiscal_year": "FY 2024",
                "revenue_crores": 240_890.5,
                "net_income_crores": 45_868.0,
            }
        ]
        assert warning is None

    def test_error_returns_empty_list_and_a_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_result = {
            "error": "financials_not_found",
            "ticker": "BADTICKER.NS",
            "message": "No financial statements found for 'BADTICKER.NS'.",
        }
        monkeypatch.setattr(
            "backend.services.analysis.fetch_income_statement",
            MagicMock(invoke=MagicMock(return_value=fake_result)),
        )

        points, warning = _fetch_financial_trend_sync("BADTICKER.NS")

        assert points == []
        assert warning is not None
        assert "No financial statements found" in warning


# ---------------------------------------------------------------------------
# get_analysis_chart_data() -- shared fixtures/helpers
# ---------------------------------------------------------------------------

_VALUATION: dict[str, Any] = {
    "pe_ratio": 28.4,
    "sector_avg_pe": 24.1,
    "peer_tickers": [],
}
_SENTIMENT: dict[str, Any] = {
    "sentiment_score": 0.42,
    "sentiment_label": "positive",
    "articles_analysed": 24,
    "positive_articles": 14,
    "negative_articles": 3,
    "neutral_articles": 7,
}
_RISK: dict[str, Any] = {
    "risk_score": 4,
    "governance_risk": 3,
    "regulatory_risk": 2,
    "financial_risk": 5,
    "concentration_risk": 6,
}


def _make_row(
    user_id: uuid.UUID,
    status: str = "completed",
    state_snapshot: Any = None,
) -> tuple[Any, ...]:
    """Build a fake asyncpg Row as a plain tuple -- indexable like the
    real Result row get_analysis_chart_data reads via row[0]..row[2]."""
    return (user_id, status, state_snapshot)


def _make_session_returning_row(row: Optional[tuple[Any, ...]]) -> AsyncMock:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture(autouse=True)
def _stub_live_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Every test in the classes below exercises get_analysis_chart_data's
    DB/ownership/status/snapshot logic, not the live-fetch functions
    themselves (those have their own TestFetchPriceHistorySync /
    TestFetchFinancialTrendSync above) -- autouse-stub both to fixed,
    warning-free data so no test needs to repeat this setup.
    """
    monkeypatch.setattr(
        "backend.services.analysis._fetch_price_history_sync",
        lambda ticker: (
            [{"date": "2026-06-18", "close": 3845.2, "volume": 1}],
            "INR",
            None,
        ),
    )
    monkeypatch.setattr(
        "backend.services.analysis._fetch_financial_trend_sync",
        lambda ticker: ([{"fiscal_year": "FY 2024", "revenue_crores": 1.0}], None),
    )


class TestGetAnalysisChartDataNotFound:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_row_exists(self) -> None:
        session = _make_session_returning_row(None)

        result = await get_analysis_chart_data(
            session, job_id=uuid.uuid4(), user_id=uuid.uuid4()
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_a_different_users_job(self) -> None:
        owner_id = uuid.uuid4()
        requester_id = uuid.uuid4()
        row = _make_row(
            user_id=owner_id,
            state_snapshot={"ticker": "TCS.NS", "company_name": "TCS"},
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_chart_data(
            session, job_id=uuid.uuid4(), user_id=requester_id
        )

        assert result is None


class TestGetAnalysisChartDataNotReady:
    @pytest.mark.asyncio
    async def test_pending_status_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="pending")
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError) as exc_info:
            await get_analysis_chart_data(session, job_id=uuid.uuid4(), user_id=user_id)
        assert exc_info.value.status == "pending"

    @pytest.mark.asyncio
    async def test_completed_but_null_snapshot_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(user_id=user_id, status="completed", state_snapshot=None)
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await get_analysis_chart_data(session, job_id=uuid.uuid4(), user_id=user_id)

    @pytest.mark.asyncio
    async def test_completed_but_missing_ticker_raises_not_ready(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id,
            status="completed",
            state_snapshot={"company_name": "TCS"},  # no "ticker" key
        )
        session = _make_session_returning_row(row)

        with pytest.raises(AnalysisNotReadyError):
            await get_analysis_chart_data(session, job_id=uuid.uuid4(), user_id=user_id)


class TestGetAnalysisChartDataSuccess:
    @pytest.mark.asyncio
    async def test_returns_all_five_sources_when_present(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id,
            state_snapshot={
                "ticker": "TCS.NS",
                "company_name": "Tata Consultancy Services",
                "valuation": _VALUATION,
                "sentiment": _SENTIMENT,
                "risk": _RISK,
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_chart_data(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.ticker == "TCS.NS"
        assert result.company_name == "Tata Consultancy Services"
        assert result.valuation == _VALUATION
        assert result.sentiment == _SENTIMENT
        assert result.risk == _RISK
        assert result.price_history != []
        assert result.financials != []
        assert result.data_warnings == []

    @pytest.mark.asyncio
    async def test_missing_valuation_is_none_with_a_warning(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id,
            state_snapshot={
                "ticker": "TCS.NS",
                "company_name": "Tata Consultancy Services",
                "sentiment": _SENTIMENT,
                "risk": _RISK,
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_chart_data(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.valuation is None
        assert any("Valuation" in w for w in result.data_warnings)
        # The other sources are unaffected.
        assert result.sentiment == _SENTIMENT
        assert result.risk == _RISK

    @pytest.mark.asyncio
    async def test_missing_sentiment_and_risk_are_none_with_warnings(self) -> None:
        user_id = uuid.uuid4()
        row = _make_row(
            user_id=user_id,
            state_snapshot={
                "ticker": "TCS.NS",
                "company_name": "Tata Consultancy Services",
                "valuation": _VALUATION,
            },
        )
        session = _make_session_returning_row(row)

        result = await get_analysis_chart_data(
            session, job_id=uuid.uuid4(), user_id=user_id
        )

        assert result is not None
        assert result.sentiment is None
        assert result.risk is None
        assert len(result.data_warnings) == 2
