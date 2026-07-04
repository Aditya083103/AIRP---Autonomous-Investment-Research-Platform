# backend/tests/unit/test_analysis_charts_router.py
"""
Unit tests for T-062: backend/routers/analysis.py's

    GET /api/v1/analysis/{job_id}/charts

A separate file from test_analysis_result_history_router.py -- T-062 is
its own task with its own acceptance criteria (all 5 chart types render
with real data) and introduces its own external-call surface (the two
LIVE yFinance fetches backend.services.analysis.get_analysis_chart_data
makes for price history and the revenue/profit trend), mirroring the
precedent that file's own docstring already set for splitting endpoints
into their own test file rather than growing one file indefinitely.

Acceptance criteria verified (from task spec):
  * All 5 chart types render with real data -- TestGetChartsSuccess
    asserts every field of price_history/financials/valuation/
    sentiment/risk reaches the response body.
  * Each chart source degrades independently rather than failing the
    whole response -- TestGetChartsPartialDegradation.

End-to-end HTTP tests against the real FastAPI app (httpx.ASGITransport),
identical approach to test_analysis_result_history_router.py, with:
  * get_async_session overridden to a small in-memory fake session
    (_FakeChartsSession) that recognises the SAME _SQL_LOAD_RESULT
    query get_analysis_result already issues -- get_analysis_chart_data
    (T-062) deliberately reuses that exact query rather than adding a
    new one, since both need only ownership/status/state_snapshot.
  * get_current_user overridden to a fixed User instance.
  * backend.services.analysis._fetch_price_history_sync and
    ._fetch_financial_trend_sync monkeypatched per-test -- these are
    the two functions that make a LIVE yFinance call
    (asyncio.to_thread-wrapped in get_analysis_chart_data), so patching
    exactly at that boundary keeps every test hermetic without needing
    to fake yfinance.Ticker/Redis underneath them.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from collections.abc import AsyncGenerator
from typing import Any, Optional, cast
import uuid

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy.sql.elements import TextClause

from backend.config import Settings
from backend.db.session import get_async_session
from backend.dependencies.auth import get_current_user
from backend.dependencies.common import get_settings_dependency
from backend.main import create_app
from backend.models.orm import User

# ---------------------------------------------------------------------------
# Fixed test data
# ---------------------------------------------------------------------------

_VALUATION: dict[str, Any] = {
    "agent_name": "valuation_agent",
    "pe_ratio": 28.4,
    "sector_avg_pe": 24.1,
    "pb_ratio": 11.2,
    "sector_avg_pb": 9.8,
    "ev_ebitda": 19.6,
    "sector_avg_ev_ebitda": 17.3,
    "peer_tickers": ["INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "valuation_verdict": "overvalued",
}

_SENTIMENT: dict[str, Any] = {
    "agent_name": "news_sentiment",
    "sentiment_score": 0.42,
    "sentiment_label": "positive",
    "articles_analysed": 24,
    "positive_articles": 14,
    "negative_articles": 3,
    "neutral_articles": 7,
}

_RISK: dict[str, Any] = {
    "agent_name": "risk_officer",
    "risk_score": 4,
    "governance_risk": 3,
    "regulatory_risk": 2,
    "financial_risk": 5,
    "concentration_risk": 6,
}

_PRICE_POINTS: list[dict[str, Any]] = [
    {"date": "2026-06-18", "close": 3845.2, "volume": 1_204_500},
    {"date": "2026-06-19", "close": 3862.55, "volume": 980_200},
]

_FINANCIAL_POINTS: list[dict[str, Any]] = [
    {
        "fiscal_year": "FY 2023",
        "revenue_crores": 225_458.0,
        "net_income_crores": 42_147.0,
    },
    {
        "fiscal_year": "FY 2024",
        "revenue_crores": 240_890.5,
        "net_income_crores": 45_868.0,
    },
]


# ---------------------------------------------------------------------------
# Fake in-memory AsyncSession -- recognises the same _SQL_LOAD_RESULT
# query get_analysis_result (T-050) already issues, since
# get_analysis_chart_data (T-062) deliberately reuses it as-is.
# ---------------------------------------------------------------------------


class _FakeRowResult:
    """Stand-in for SQLAlchemy's Result -- fetchone() only."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeChartsSession:
    """
    In-memory fake of AsyncSession supporting exactly the one raw
    text() query backend.services.analysis.get_analysis_chart_data
    issues -- the pre-existing _SQL_LOAD_RESULT (identical to the one
    GET /result uses).
    """

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, tuple[Any, ...]] = {}

    async def execute(self, statement: Any, params: Any = None) -> Any:
        assert isinstance(statement, TextClause), (
            "get_analysis_chart_data issues only the pre-existing "
            "_SQL_LOAD_RESULT raw text() query -- no ORM Select."
        )
        job_id = uuid.UUID(str(params["job_id"]))
        row = self.rows.get(job_id)
        return _FakeRowResult(row)


def _make_session_override(shared: _FakeChartsSession) -> Any:
    """Zero-argument async generator function -- see
    test_auth_router.py's docstring for why a bare lambda does not work
    as a dependency_overrides value for an async-generator dependency."""

    async def _override() -> AsyncGenerator[_FakeChartsSession, None]:
        yield shared

    return _override


#: Sentinel distinguishing "caller did not pass this kwarg -- use the
#: canned default" from "caller explicitly passed None to simulate
#: this agent's output being absent from the snapshot" -- a mutable
#: dict literal (e.g. ``= _VALUATION``) is not a safe default
#: parameter value (flake8-bugbear B006), even though nothing here
#: mutates it.
_UNSET: Any = object()


def _seed_chart_row(
    fake_session: _FakeChartsSession,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "completed",
    ticker: Optional[str] = "TCS.NS",
    company_name: Optional[str] = "Tata Consultancy Services",
    valuation: Any = _UNSET,
    sentiment: Any = _UNSET,
    risk: Any = _UNSET,
) -> None:
    """Populate ``rows`` with the exact 3-tuple shape
    get_analysis_chart_data reads via row[0]..row[2] (user_id, status,
    state_snapshot). Pass ``valuation=None``/``sentiment=None``/
    ``risk=None`` to simulate that agent's output being absent from
    the snapshot (TestGetChartsPartialDegradation); omit a kwarg
    entirely to use its canned default value instead."""
    if valuation is _UNSET:
        valuation = _VALUATION
    if sentiment is _UNSET:
        sentiment = _SENTIMENT
    if risk is _UNSET:
        risk = _RISK

    snapshot: Optional[dict[str, Any]] = None
    if ticker is not None or company_name is not None:
        snapshot = {"ticker": ticker, "company_name": company_name}
        if valuation is not None:
            snapshot["valuation"] = valuation
        if sentiment is not None:
            snapshot["sentiment"] = sentiment
        if risk is not None:
            snapshot["risk"] = risk
    fake_session.rows[job_id] = (user_id, status, snapshot)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session() -> _FakeChartsSession:
    return _FakeChartsSession()


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="analyst@example.com",
        password_hash="$2b$12$irrelevant-for-this-test",
        is_active=True,
    )


@pytest.fixture
def mock_live_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Patches the two functions that make a LIVE yFinance call
    (backend.services.analysis._fetch_price_history_sync and
    ._fetch_financial_trend_sync) to return fixed data with no
    warning. Individual tests override either patch again to exercise
    the degraded/failed path instead.
    """
    monkeypatch.setattr(
        "backend.services.analysis._fetch_price_history_sync",
        lambda ticker: (_PRICE_POINTS, "INR", None),
    )
    monkeypatch.setattr(
        "backend.services.analysis._fetch_financial_trend_sync",
        lambda ticker: (_FINANCIAL_POINTS, None),
    )


@pytest.fixture
async def client(
    fake_session: _FakeChartsSession,
    current_user: User,
    test_settings: Settings,
    mock_live_fetches: None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_async_session] = _make_session_override(fake_session)
    app.dependency_overrides[get_settings_dependency] = lambda: test_settings
    app.dependency_overrides[get_current_user] = lambda: current_user

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/charts -- not found / auth
# ---------------------------------------------------------------------------


class TestGetChartsNotFound:
    @pytest.mark.asyncio
    async def test_unknown_job_id_returns_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/v1/analysis/{uuid.uuid4()}/charts")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_job_id_returns_422(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/v1/analysis/not-a-uuid/charts")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_job_belonging_to_a_different_user_returns_404(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=uuid.uuid4())

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_authentication(
        self,
        fake_session: _FakeChartsSession,
        test_settings: Settings,
        mock_live_fetches: None,
    ) -> None:
        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{uuid.uuid4()}/charts")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/charts -- not ready yet
# ---------------------------------------------------------------------------


class TestGetChartsNotReady:
    @pytest.mark.asyncio
    async def test_pending_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, status="pending")

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_running_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, status="running")

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_failed_job_returns_409(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, status="failed")

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_409_detail_names_the_actual_status(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, status="running")

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert "running" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_completed_but_missing_ticker_is_treated_as_not_ready(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        # status='completed' but the snapshot has no ticker -- should
        # not happen given the Planner node's contract, but must
        # surface as 409, never a 500.
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, ticker=None)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/charts -- success, all 5 chart types
# ---------------------------------------------------------------------------


class TestGetChartsSuccess:
    @pytest.mark.asyncio
    async def test_returns_200_with_every_top_level_field(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "TCS.NS"
        assert body["company_name"] == "Tata Consultancy Services"
        assert body["price_currency"] == "INR"
        assert body["data_warnings"] == []

    @pytest.mark.asyncio
    async def test_price_history_matches_the_live_fetch(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.json()["price_history"] == _PRICE_POINTS

    @pytest.mark.asyncio
    async def test_financials_match_the_live_fetch(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        assert response.json()["financials"] == _FINANCIAL_POINTS

    @pytest.mark.asyncio
    async def test_valuation_matches_the_snapshot(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        valuation = response.json()["valuation"]
        assert valuation["pe_ratio"] == 28.4
        assert valuation["sector_avg_pe"] == 24.1
        assert valuation["peer_tickers"] == ["INFY.NS", "WIPRO.NS", "HCLTECH.NS"]

    @pytest.mark.asyncio
    async def test_sentiment_matches_the_snapshot(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        sentiment = response.json()["sentiment"]
        assert sentiment["sentiment_score"] == 0.42
        assert sentiment["articles_analysed"] == 24

    @pytest.mark.asyncio
    async def test_risk_matches_the_snapshot(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        risk = response.json()["risk"]
        assert risk["risk_score"] == 4
        assert risk["governance_risk"] == 3
        assert risk["concentration_risk"] == 6


# ---------------------------------------------------------------------------
# GET /api/v1/analysis/{job_id}/charts -- each chart source degrades
# independently rather than failing the whole response
# ---------------------------------------------------------------------------


class TestGetChartsPartialDegradation:
    @pytest.mark.asyncio
    async def test_missing_valuation_returns_null_plus_a_warning(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, valuation=None)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        body = response.json()
        assert response.status_code == 200
        assert body["valuation"] is None
        assert any("Valuation" in w for w in body["data_warnings"])
        # The other four sources are unaffected.
        assert body["sentiment"] is not None
        assert body["risk"] is not None
        assert body["price_history"] == _PRICE_POINTS

    @pytest.mark.asyncio
    async def test_missing_sentiment_returns_null_plus_a_warning(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, sentiment=None)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        body = response.json()
        assert response.status_code == 200
        assert body["sentiment"] is None
        assert any("Sentiment" in w for w in body["data_warnings"])

    @pytest.mark.asyncio
    async def test_missing_risk_returns_null_plus_a_warning(
        self,
        client: httpx.AsyncClient,
        fake_session: _FakeChartsSession,
        current_user: User,
    ) -> None:
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id, risk=None)

        response = await client.get(f"/api/v1/analysis/{job_id}/charts")

        body = response.json()
        assert response.status_code == 200
        assert body["risk"] is None
        assert any("Risk" in w for w in body["data_warnings"])

    @pytest.mark.asyncio
    async def test_failed_price_fetch_returns_empty_list_plus_a_warning(
        self,
        fake_session: _FakeChartsSession,
        current_user: User,
        test_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "backend.services.analysis._fetch_price_history_sync",
            lambda ticker: ([], "INR", "Price history unavailable: rate limited"),
        )
        monkeypatch.setattr(
            "backend.services.analysis._fetch_financial_trend_sync",
            lambda ticker: (_FINANCIAL_POINTS, None),
        )
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        app.dependency_overrides[get_current_user] = lambda: current_user
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{job_id}/charts")

        body = response.json()
        assert response.status_code == 200
        assert body["price_history"] == []
        assert any("Price history" in w for w in body["data_warnings"])
        # The other four sources are unaffected.
        assert body["financials"] == _FINANCIAL_POINTS
        assert body["valuation"] is not None

    @pytest.mark.asyncio
    async def test_failed_financials_fetch_returns_empty_list_plus_a_warning(
        self,
        fake_session: _FakeChartsSession,
        current_user: User,
        test_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "backend.services.analysis._fetch_price_history_sync",
            lambda ticker: (_PRICE_POINTS, "INR", None),
        )
        monkeypatch.setattr(
            "backend.services.analysis._fetch_financial_trend_sync",
            lambda ticker: ([], "Revenue/profit trend unavailable: ticker not found"),
        )
        job_id = uuid.uuid4()
        _seed_chart_row(fake_session, job_id, user_id=current_user.id)

        app: FastAPI = create_app()
        app.dependency_overrides[get_async_session] = _make_session_override(
            fake_session
        )
        app.dependency_overrides[get_settings_dependency] = lambda: test_settings
        app.dependency_overrides[get_current_user] = lambda: current_user
        transport = httpx.ASGITransport(app=cast(Any, app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            response = await ac.get(f"/api/v1/analysis/{job_id}/charts")

        body = response.json()
        assert response.status_code == 200
        assert body["financials"] == []
        assert any("Revenue/profit trend" in w for w in body["data_warnings"])
        # The other four sources are unaffected.
        assert body["price_history"] == _PRICE_POINTS
